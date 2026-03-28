import torch
import torch.nn as nn
from tqdm import tqdm

from utils import compute_metrics


def teacher_forward_batch(teacher, seqs, graphs, valid_mask, device):
    t_logits_list, z_fusion_list, valid_idx = [], [], []
    for i, (seq, g, valid) in enumerate(zip(seqs, graphs, valid_mask)):
        if not valid:
            continue
        with torch.no_grad():
            t_logits, z_fusion = teacher([seq], g, device)
        t_logits_list.append(t_logits)
        z_fusion_list.append(z_fusion)
        valid_idx.append(i)
    return t_logits_list, z_fusion_list, valid_idx


def student_forward_batch(student, seqs, valid_idx, device):
    valid_seqs = [seqs[i] for i in valid_idx]
    data       = [(f"seq{i}", s) for i, s in enumerate(valid_seqs)]
    _, _, tokens = student.esm_enc.batch_converter(data)
    tokens  = tokens.to(device)
    results = student.esm_enc.esm_model(tokens, repr_layers=[12], return_contacts=False)
    token_repr = results["representations"][12]

    s_logits_list, z_student_list = [], []
    for i, seq in enumerate(valid_seqs):
        z = student.esm_enc.proj(token_repr[i, 1:len(seq) + 1, :]).mean(0)
        s_logits_list.append(student.head(z))
        z_student_list.append(z)
    return s_logits_list, z_student_list


def train_teacher_epoch(teacher, optimizer, loader, device, epoch: int):
    teacher.train()
    for layer in teacher.esm_enc.esm_model.layers:
        if not any(p.requires_grad for p in layer.parameters()):
            layer.eval()

    ce_loss    = nn.CrossEntropyLoss()
    total_loss = 0.0
    correct    = 0
    n          = 0

    pbar = tqdm(loader, desc=f"Teacher Epoch {epoch}", ncols=110)
    for step, (seqs, graphs, labels, valid_mask) in enumerate(pbar):
        batch_loss = torch.tensor(0.0, device=device, requires_grad=True)
        nb = 0
        for i, (seq, g, valid) in enumerate(zip(seqs, graphs, valid_mask)):
            if not valid:
                continue
            logits, _ = teacher([seq], g, device)
            loss       = ce_loss(logits.unsqueeze(0), labels[i:i + 1].to(device))
            batch_loss = batch_loss + loss
            correct   += int(logits.argmax().item() == labels[i].item())
            n         += 1
            nb        += 1

        if nb == 0:
            continue

        batch_loss = batch_loss / nb
        optimizer.zero_grad()
        batch_loss.backward()
        nn.utils.clip_grad_norm_(filter(lambda p: p.requires_grad, teacher.parameters()), 1.0)
        optimizer.step()
        total_loss += batch_loss.item()

        pbar.set_postfix({
            "loss": f"{total_loss / (step + 1):.4f}",
            "acc":  f"{correct / max(n, 1):.4f}",
        })

    return total_loss / max(len(loader), 1), correct / max(n, 1)


def train_student_epoch(teacher, student, criterion, optimizer, loader, device, epoch: int):
    teacher.eval()
    student.train()
    total_loss = 0.0
    correct    = 0
    n          = 0

    pbar = tqdm(loader, desc=f"Student Epoch {epoch}", ncols=110)
    for step, (seqs, graphs, labels, valid_mask) in enumerate(pbar):
        t_logits_list, z_fusion_list, valid_idx = teacher_forward_batch(
            teacher, seqs, graphs, valid_mask, device
        )
        if not valid_idx:
            continue

        s_logits_list, z_student_list = student_forward_batch(student, seqs, valid_idx, device)

        loss     = torch.tensor(0.0, device=device, requires_grad=True)
        ld_accum = {"l_task": 0.0, "l_logits": 0.0, "l_fusion": 0.0, "total": 0.0}
        nb = len(valid_idx)

        for k, i in enumerate(valid_idx):
            l, ld  = criterion(s_logits_list[k], t_logits_list[k],
                               z_student_list[k], z_fusion_list[k],
                               labels[i].to(device))
            loss   = loss + l / nb
            for key in ld_accum:
                ld_accum[key] += ld[key] / nb

        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(student.parameters(), 1.0)
        optimizer.step()

        for k, i in enumerate(valid_idx):
            correct += int(s_logits_list[k].argmax().item() == labels[i].item())
            n += 1
        total_loss += ld_accum["total"]

        pbar.set_postfix({
            "loss": f"{total_loss / (step + 1):.4f}",
            "acc":  f"{correct / max(n, 1):.4f}",
            "task": f"{ld_accum['l_task']:.4f}",
            "kl":   f"{ld_accum['l_logits']:.4f}",
            "mse":  f"{ld_accum['l_fusion']:.4f}",
        })

    return total_loss / max(len(loader), 1), correct / max(n, 1)


@torch.no_grad()
def evaluate_student(student, loader, device, split: str = "Val") -> dict:
    student.eval()
    all_preds, all_labels, all_probs = [], [], []

    pbar = tqdm(loader, desc=f"[{split}]", ncols=110)
    for seqs, graphs, labels, valid_mask in pbar:
        valid_idx = [i for i, v in enumerate(valid_mask) if v]
        if not valid_idx:
            continue
        s_logits_list, _ = student_forward_batch(student, seqs, valid_idx, device)
        for k, i in enumerate(valid_idx):
            logits = s_logits_list[k]
            all_probs.append(torch.softmax(logits, dim=-1)[1].item())
            all_preds.append(logits.argmax().item())
            all_labels.append(labels[i].item())
        acc = sum(p == l for p, l in zip(all_preds, all_labels)) / max(len(all_preds), 1)
        pbar.set_postfix({"acc": f"{acc:.4f}"})

    return compute_metrics(all_labels, all_preds, all_probs)


@torch.no_grad()
def evaluate_teacher(teacher, loader, device, split: str = "Val") -> dict:
    teacher.eval()
    all_preds, all_labels, all_probs = [], [], []

    pbar = tqdm(loader, desc=f"[Teacher {split}]", ncols=110)
    for seqs, graphs, labels, valid_mask in pbar:
        for i, (seq, g, valid) in enumerate(zip(seqs, graphs, valid_mask)):
            if not valid:
                continue
            logits, _ = teacher([seq], g, device)
            all_probs.append(torch.softmax(logits, dim=-1)[1].item())
            all_preds.append(logits.argmax().item())
            all_labels.append(labels[i].item())

    return compute_metrics(all_labels, all_preds, all_probs)
