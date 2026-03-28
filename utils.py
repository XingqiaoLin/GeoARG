import re
import random
import numpy as np
import torch

SEED = 42
MAX_SEQ_LEN = 1022


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def clean_seq(s: str) -> str:
    s = (s or "").upper().replace("/", ":")
    s = re.sub(r"[^A-Z:]", "", s)
    s = re.sub(r":+", ":", s).strip(":")
    return s[:MAX_SEQ_LEN]


def clean_header(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("._-")
    return s


def compute_metrics(all_labels, all_preds, all_probs) -> dict:
    from sklearn.metrics import roc_auc_score, matthews_corrcoef

    labels = np.array(all_labels)
    preds  = np.array(all_preds)
    probs  = np.array(all_probs)

    acc = (preds == labels).mean()
    mcc = matthews_corrcoef(labels, preds)

    tp = ((preds == 1) & (labels == 1)).sum()
    tn = ((preds == 0) & (labels == 0)).sum()
    fp = ((preds == 1) & (labels == 0)).sum()
    fn = ((preds == 0) & (labels == 1)).sum()

    sensitivity = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    precision   = tp / max(tp + fp, 1)
    f1 = 2 * precision * sensitivity / max(precision + sensitivity, 1e-8)

    try:
        auroc = roc_auc_score(labels, probs)
    except Exception:
        auroc = float("nan")

    return {
        "acc":         round(float(acc),         4),
        "mcc":         round(float(mcc),         4),
        "auroc":       round(float(auroc),        4),
        "sensitivity": round(float(sensitivity),  4),
        "specificity": round(float(specificity),  4),
        "precision":   round(float(precision),    4),
        "f1":          round(float(f1),           4),
    }


def print_metrics(tag: str, m: dict) -> None:
    print(
        f"  {tag} | acc={m['acc']:.4f}  mcc={m['mcc']:.4f}"
        f"  auroc={m['auroc']:.4f}  sen={m['sensitivity']:.4f}"
        f"  spe={m['specificity']:.4f}  f1={m['f1']:.4f}"
    )
