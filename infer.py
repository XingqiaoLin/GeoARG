#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from typing import List, Optional, Tuple

import pandas as pd
import torch
from Bio import SeqIO
from transformers import AutoConfig, AutoTokenizer, EsmForSequenceClassification


def read_fasta_records(paths: List[str]) -> Tuple[List[str], List[str]]:
    seq_ids: List[str] = []
    seqs: List[str] = []
    for p in paths:
        with open(p, "r") as handle:
            for rec in SeqIO.parse(handle, "fasta"):
                sid = (rec.id or "").strip()
                if not sid:
                    sid = (rec.description or "").split()[0]
                seq = str(rec.seq).strip().upper()
                if not sid or not seq:
                    continue
                seq_ids.append(sid)
                seqs.append(seq)
    return seq_ids, seqs


@torch.inference_mode()
def batched_predict_to_rows(
    model,
    tokenizer,
    seq_ids: List[str],
    seqs: List[str],
    batch_size: int,
    device: str,
    thr: float,
    max_length: Optional[int],
    progress_every: int,
    labels: Optional[List[str]],
    topk: int,
    evidential: bool,
) -> List[dict]:
    rows: List[dict] = []
    model.eval()

    n = len(seqs)
    for i in range(0, n, batch_size):
        batch_ids = seq_ids[i : i + batch_size]
        batch_seqs = seqs[i : i + batch_size]

        enc = tokenizer(
            batch_seqs,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_length,
        )
        enc = {k: v.to(device) for k, v in enc.items()}
        out = model(**enc)

        logits = out.logits
        if logits.ndim != 2:
            raise ValueError(f"Unexpected logits shape: {tuple(logits.shape)}")

        num_labels = int(logits.shape[1])
        if num_labels in (1, 2):
            if num_labels == 2:
                prob = torch.softmax(logits, dim=-1)[:, 1]
            else:
                prob = torch.sigmoid(logits[:, 0])
            prob_np = prob.detach().float().cpu().numpy()
            pred = (prob_np >= thr).astype(int)
            for sid, p, y in zip(batch_ids, prob_np, pred):
                rows.append({"seq_id": sid, "prob": float(p), "pred": int(y)})
        else:
            if evidential:
                evidence = torch.nn.functional.softplus(logits)
                alpha = evidence + 1.0
                s = alpha.sum(dim=-1, keepdim=True)
                probs = alpha / (s + 1e-12)
                uncertainty = (float(num_labels) / (s.squeeze(-1) + 1e-12)).clamp(0.0, 1.0)
                conf = (1.0 - uncertainty).clamp(0.0, 1.0)
            else:
                probs = torch.softmax(logits, dim=-1)
                uncertainty = None
                conf = None
            topk_eff = max(1, min(int(topk), num_labels))
            topv, topi = torch.topk(probs, k=topk_eff, dim=-1)

            pred_idx = torch.argmax(probs, dim=-1)
            pred_prob = probs[torch.arange(probs.size(0), device=probs.device), pred_idx]

            pred_idx_np = pred_idx.detach().cpu().numpy().astype(int)
            pred_prob_np = pred_prob.detach().float().cpu().numpy()
            topi_np = topi.detach().cpu().numpy().astype(int)
            topv_np = topv.detach().float().cpu().numpy()

            for j, sid in enumerate(batch_ids):
                pi = int(pred_idx_np[j])
                pl = labels[pi] if labels and 0 <= pi < len(labels) else str(pi)
                tk_labels = []
                for k in range(topk_eff):
                    idx = int(topi_np[j, k])
                    tk_labels.append(labels[idx] if labels and 0 <= idx < len(labels) else str(idx))
                row = {
                    "seq_id": sid,
                    "pred_label": pl,
                    "pred_idx": pi,
                    "pred_prob": float(pred_prob_np[j]),
                    "topk_labels": "|".join(tk_labels),
                    "topk_probs": "|".join(f"{float(x):.6f}" for x in topv_np[j].tolist()),
                }
                if evidential and uncertainty is not None and conf is not None:
                    row["uncertainty"] = float(uncertainty[j].detach().float().cpu().item())
                    row["conf"] = float(conf[j].detach().float().cpu().item())
                rows.append(row)

        if progress_every > 0:
            done = min(i + batch_size, n)
            if done % progress_every == 0 or done == n:
                if "pred" in rows[0]:
                    pos = int(sum(r["pred"] for r in rows))
                    print(
                        f"[INFO] progress {done}/{n}  pred=1 so far: {pos}/{len(rows)} ({pos/max(1,len(rows))*100:.2f}%)"
                    )
                else:
                    print(f"[INFO] progress {done}/{n}  done")

    return rows


def write_rows_to_csv(path: str, rows: List[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as f:
        if rows and "pred" in rows[0]:
            fieldnames = ["seq_id", "prob", "pred"]
        else:
            fieldnames = ["seq_id", "pred_label", "pred_idx", "pred_prob", "topk_labels", "topk_probs"]
            if rows and "conf" in rows[0]:
                fieldnames += ["conf", "uncertainty"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--fasta", nargs="+", required=True, help="Input protein FASTA file(s).")
    p.add_argument(
        "--base_model",
        default="facebook/esm2_t12_35M_UR50D",
        help="HF model name or local path.",
    )
    p.add_argument(
        "--local_files_only",
        action="store_true",
        help="Force Transformers/HF Hub to load from local cache only (no network).",
    )
    p.add_argument(
        "--max_length",
        type=int,
        default=1022,
        help="Tokenizer max_length for truncation. For ESM2, 1022 is the standard safe value.",
    )
    p.add_argument(
        "--dtype",
        choices=["float32", "float16", "bfloat16"],
        default="float32",
        help="Model dtype. Default: float16 on CUDA, float32 on CPU.",
    )
    p.add_argument(
        "--labels_file",
        default=None,
        help=(
            "Optional label list file (one label per line). If provided, infer will initialize the base model "
            "with num_labels=len(labels) and map indices to label strings for multi-class outputs."
        ),
    )
    p.add_argument("--topk", type=int, default=5, help="Top-k classes to output for multi-class models.")
    p.add_argument(
        "--evidential",
        action="store_true",
        help="For multi-class heads only: interpret logits as evidence (Dirichlet) and output conf/uncertainty.",
    )
    p.add_argument("--out_csv", required=True, help="Output CSV path.")
    p.add_argument("--thr", type=float, default=0.5, help="Decision threshold on prob.")
    p.add_argument("--batch_size", type=int, default=4)
    p.add_argument("--progress_every", type=int, default=200, help="Print progress every N sequences (0=off).")
    p.add_argument(
        "--device",
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="cuda / cpu",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out_csv)), exist_ok=True)

    if args.local_files_only:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

    seq_ids, seqs = read_fasta_records(args.fasta)
    if len(seqs) == 0:
        raise SystemExit("[ERROR] No sequences found in input FASTA(s).")

    device = args.device
    torch_dtype = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}[args.dtype]

    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model,
        do_lower_case=False,
        local_files_only=bool(args.local_files_only),
    )

    labels: Optional[List[str]] = None
    if args.labels_file:
        with open(args.labels_file, "r", encoding="utf-8") as f:
            labels = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        if len(labels) < 2:
            raise SystemExit(f"[ERROR] labels_file has too few labels: {args.labels_file}")
        label2id = {lab: i for i, lab in enumerate(labels)}
        id2label = {i: lab for i, lab in enumerate(labels)}
        config = AutoConfig.from_pretrained(
            args.base_model,
            num_labels=len(labels),
            label2id=label2id,
            id2label=id2label,
            local_files_only=bool(args.local_files_only),
        )
        model = EsmForSequenceClassification.from_pretrained(
            args.base_model,
            config=config,
            local_files_only=bool(args.local_files_only),
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=False,
        )
    else:
        model = EsmForSequenceClassification.from_pretrained(
            args.base_model,
            local_files_only=bool(args.local_files_only),
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=False,
        )

    model.to(device)
    if str(device).startswith("cuda") and args.dtype == "float16":
        model.half()

    rows = batched_predict_to_rows(
        model=model,
        tokenizer=tokenizer,
        seq_ids=seq_ids,
        seqs=seqs,
        batch_size=int(args.batch_size),
        device=device,
        thr=float(args.thr),
        max_length=int(args.max_length) if int(args.max_length) > 0 else None,
        progress_every=int(args.progress_every),
        labels=labels,
        topk=int(args.topk),
        evidential=bool(args.evidential),
    )
    write_rows_to_csv(args.out_csv, rows)
    print(f"[INFO] Predictions saved to {args.out_csv}")
    if rows and "pred" in rows[0]:
        pos = int(sum(r["pred"] for r in rows))
        print(f"[INFO] pred=1: {pos}/{len(rows)} ({pos/len(rows)*100:.2f}%) thr={args.thr}")
    else:
        vc = pd.Series([r["pred_label"] for r in rows]).value_counts()
        print("[INFO] Top predicted labels:")
        print(vc.head(10).to_string())


if __name__ == "__main__":
    main()
