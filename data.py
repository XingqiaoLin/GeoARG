import csv
import math
import os

import numpy as np
import torch
from Bio.PDB import PDBParser
from torch.utils.data import Dataset

from utils import clean_seq, clean_header


class GeoARGDataset(Dataset):
    def __init__(self, csv_path: str, pdb_dir: str):
        self.records: list[tuple[str, str, int]] = []

        with open(csv_path, newline="") as f:
            reader     = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            has_header = "header" in fieldnames
            rows       = list(reader)

        seen: dict[str, int] = {}
        for idx, row in enumerate(rows):
            seq = clean_seq(row.get("sequence", ""))
            h   = clean_header(row.get("header", "") if has_header else str(idx)) or str(idx)
            n   = seen.get(h, 0)
            seen[h] = n + 1
            basename = h if n == 0 else f"{h}_{idx}"
            pdb_path = os.path.join(pdb_dir, f"{basename}.pdb")
            try:
                label = int(row.get("label1", 0))
            except (ValueError, TypeError):
                label = 0
            if not seq or not os.path.exists(pdb_path):
                continue
            self.records.append((seq, pdb_path, label))

        pos = sum(1 for _, _, l in self.records if l == 1)
        neg = sum(1 for _, _, l in self.records if l == 0)
        print(f"Dataset: {len(self.records)} samples | pos={pos} neg={neg}")

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int):
        return self.records[idx]


_THREE2ONE = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F",
    "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K", "LEU": "L",
    "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R",
    "SER": "S", "THR": "T", "VAL": "V", "TRP": "W", "TYR": "Y",
}
_AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"
_AA2IDX   = {a: i for i, a in enumerate(_AA_ORDER)}


def _get_dihedral(p0, p1, p2, p3) -> float:
    b1 = p1 - p0; b2 = p2 - p1; b3 = p3 - p2
    n1 = np.cross(b1, b2); n2 = np.cross(b2, b3)
    nn1 = np.linalg.norm(n1); nn2 = np.linalg.norm(n2)
    if nn1 < 1e-6 or nn2 < 1e-6:
        return 0.0
    n1 /= nn1; n2 /= nn2
    return float(np.arctan2(
        np.dot(np.cross(n1, n2), b2 / np.linalg.norm(b2)),
        np.clip(np.dot(n1, n2), -1, 1),
    ))


def _local_frame(v: np.ndarray) -> np.ndarray:
    v = v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-8)
    perp = np.where(
        np.abs(v[:, 0:1]) < 0.9,
        np.tile([1, 0, 0], (len(v), 1)),
        np.tile([0, 1, 0], (len(v), 1)),
    ).astype(np.float32)
    u = np.cross(v, perp)
    u = u / (np.linalg.norm(u, axis=-1, keepdims=True) + 1e-8)
    return np.stack([v, u, np.cross(v, u)], axis=-1)


def parse_pdb_to_graph(pdb_path: str, ca_cutoff: float = 8.0) -> dict | None:
    parser    = PDBParser(QUIET=True)
    structure = parser.get_structure("prot", pdb_path)
    model     = next(structure.get_models())

    residues = [
        res for chain in model for res in chain
        if res.id[0] == " " and "CA" in res
    ]
    if len(residues) < 2:
        return None

    N         = len(residues)
    coords    = np.zeros((N, 3),  dtype=np.float32)
    one_hot   = np.zeros((N, 20), dtype=np.float32)
    dihedrals = np.zeros((N, 6),  dtype=np.float32)
    plddt_arr = np.zeros((N,),    dtype=np.float32)

    for i, res in enumerate(residues):
        ca           = res["CA"]
        coords[i]    = ca.get_vector().get_array()
        plddt_arr[i] = ca.get_bfactor() / 100.0
        aa = _THREE2ONE.get(res.get_resname().strip(), "G")
        if aa in _AA2IDX:
            one_hot[i, _AA2IDX[aa]] = 1.0

    for i in range(1, N - 1):
        try:
            prev, curr, nxt = residues[i - 1], residues[i], residues[i + 1]
            if all("C" in r and "N" in r and "CA" in r for r in [prev, curr]):
                phi = _get_dihedral(
                    prev["C"].get_vector().get_array(),
                    curr["N"].get_vector().get_array(),
                    curr["CA"].get_vector().get_array(),
                    curr["C"].get_vector().get_array(),
                )
                dihedrals[i, 0] = math.sin(phi)
                dihedrals[i, 1] = math.cos(phi)
            if all("N" in r and "CA" in r and "C" in r for r in [curr, nxt]):
                psi = _get_dihedral(
                    curr["N"].get_vector().get_array(),
                    curr["CA"].get_vector().get_array(),
                    curr["C"].get_vector().get_array(),
                    nxt["N"].get_vector().get_array(),
                )
                dihedrals[i, 2] = math.sin(psi)
                dihedrals[i, 3] = math.cos(psi)
        except Exception:
            pass

    node_feat = np.concatenate([one_hot, dihedrals, plddt_arr[:, None]], axis=1)

    dist_mat    = np.linalg.norm(coords[:, None] - coords[None, :], axis=-1)
    src, dst    = np.where((dist_mat < ca_cutoff) & (dist_mat > 0))
    rbf_centers = np.linspace(0, ca_cutoff, 16).astype(np.float32)
    rbf_sigma   = (ca_cutoff / 16) * 0.5

    diffs    = coords[dst] - coords[src]
    dists    = np.linalg.norm(diffs, axis=-1, keepdims=True)
    unit_dir = diffs / (dists + 1e-8)
    rbf      = np.exp(-((dists - rbf_centers) ** 2) / (2 * rbf_sigma ** 2))
    rel_rot  = (
        _local_frame(unit_dir).transpose(0, 2, 1) @ _local_frame(-unit_dir)
    ).reshape(-1, 9)

    edge_feat = np.concatenate([rbf, unit_dir, rel_rot], axis=-1)

    return {
        "node_feat":  torch.tensor(node_feat),
        "edge_index": torch.tensor(np.stack([src, dst], axis=0), dtype=torch.long),
        "edge_feat":  torch.tensor(edge_feat),
        "plddt":      torch.tensor(plddt_arr),
    }


def collate_fn(batch):
    seqs, pdb_paths, labels = zip(*batch)
    graphs, valid_mask = [], []
    for p in pdb_paths:
        g = parse_pdb_to_graph(p)
        graphs.append(g)
        valid_mask.append(g is not None)
    return list(seqs), graphs, torch.tensor(labels, dtype=torch.long), valid_mask
