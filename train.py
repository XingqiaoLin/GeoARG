import json
import os
import random

import torch
from safetensors.torch import load_file, save_file
from torch.utils.data import DataLoader, Subset

from data import GeoARGDataset, collate_fn
from models import DistillationLoss, GeoARGStudent, GeoARGTeacher
from trainer import (
    evaluate_student,
    evaluate_teacher,
    train_student_epoch,
    train_teacher_epoch,
)
from utils import SEED, print_metrics, set_seed

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

TRAIN_CSV = "/content/drive/MyDrive/GeoARG/arg_train.csv"
TEST_CSV  = "/content/drive/MyDrive/GeoARG/arg_test.csv"
TRAIN_PDB = "/content/drive/MyDrive/GeoARG/train_pdbs"
TEST_PDB  = "/content/drive/MyDrive/GeoARG/test_pdbs"
SAVE_DIR  = "/content/drive/MyDrive/GeoARG"

TEACHER_EPOCHS = 10
STUDENT_EPOCHS = 10
BATCH_SIZE     = 2


def build_dataloaders():
    full_train   = GeoARGDataset(TRAIN_CSV, TRAIN_PDB)
    test_dataset = GeoARGDataset(TEST_CSV,  TEST_PDB)

    n_total = len(full_train)
    n_val   = n_total // 8
    indices = list(range(n_total))
    random.shuffle(indices)

    train_dataset = Subset(full_train, indices[n_val:])
    val_dataset   = Subset(full_train, indices[:n_val])
    print(f"Train={len(train_dataset)}  Val={len(val_dataset)}  Test={len(test_dataset)}")

    kwargs = dict(batch_size=BATCH_SIZE, collate_fn=collate_fn, num_workers=0)
    return (
        DataLoader(train_dataset, shuffle=True,  **kwargs),
        DataLoader(val_dataset,   shuffle=False, **kwargs),
        DataLoader(test_dataset,  shuffle=False, **kwargs),
    )


def phase1_teacher(train_loader, val_loader, device):
    print("\n" + "=" * 60)
    print("Phase 1: Teacher  (ESM2 partial finetune, last 4 layers)")
    print("=" * 60)

    teacher = GeoARGTeacher(num_classes=2, proj_dim=512, freeze_esm=True, unfreeze_last_n=4).to(device)

    esm_params   = [p for p in teacher.esm_enc.esm_model.parameters() if p.requires_grad]
    other_params = (
        list(teacher.esm_enc.proj.parameters())
        + list(teacher.gnn.parameters())
        + list(teacher.fusion.parameters())
        + list(teacher.head.parameters())
    )
    optimizer = torch.optim.AdamW(
        [{"params": esm_params, "lr": 1e-5}, {"params": other_params, "lr": 1e-4}],
        weight_decay=1e-2,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=TEACHER_EPOCHS, eta_min=1e-6)

    best_f1 = 0.0
    for epoch in range(1, TEACHER_EPOCHS + 1):
        print(f"\n----- Teacher Epoch {epoch}/{TEACHER_EPOCHS} -----")
        torch.cuda.empty_cache()
        train_teacher_epoch(teacher, optimizer, train_loader, device, epoch)
        torch.cuda.empty_cache()
        val_m = evaluate_teacher(teacher, val_loader, device, split="Val")
        scheduler.step()
        print_metrics("Teacher Val", val_m)

        if val_m["f1"] > best_f1:
            best_f1 = val_m["f1"]
            save_file(
                {k: v.float() for k, v in teacher.state_dict().items()},
                os.path.join(SAVE_DIR, "teacher_best.safetensors"),
            )
            with open(os.path.join(SAVE_DIR, "teacher_best_meta.json"), "w") as f:
                json.dump({"epoch": epoch, **{k: str(v) for k, v in val_m.items()}}, f, indent=2)
            print(f"  ✓ Teacher saved  val_f1={best_f1:.4f}")

    print("\nLoading best Teacher for distillation...")
    teacher.load_state_dict(load_file(os.path.join(SAVE_DIR, "teacher_best.safetensors")))
    teacher.eval()
    return teacher, best_f1


def phase2_student(teacher, train_loader, val_loader, device):
    print("\n" + "=" * 60)
    print("Phase 2: Student distillation")
    print("=" * 60)

    student   = GeoARGStudent(num_classes=2, proj_dim=512).to(device)
    optimizer = torch.optim.AdamW(student.parameters(), lr=1e-4, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=STUDENT_EPOCHS, eta_min=1e-6)
    criterion = DistillationLoss(lambda1=1.0, lambda2=0.1, temperature=4.0)

    best_f1 = 0.0
    for epoch in range(1, STUDENT_EPOCHS + 1):
        print(f"\n----- Student Epoch {epoch}/{STUDENT_EPOCHS} -----")
        torch.cuda.empty_cache()
        train_student_epoch(teacher, student, criterion, optimizer, train_loader, device, epoch)
        torch.cuda.empty_cache()
        val_m = evaluate_student(student, val_loader, device, split="Val")
        scheduler.step()
        print_metrics("Student Val", val_m)

        if val_m["f1"] > best_f1:
            best_f1 = val_m["f1"]
            save_file(student.state_dict(), os.path.join(SAVE_DIR, "student_best.safetensors"))
            with open(os.path.join(SAVE_DIR, "student_best_meta.json"), "w") as f:
                json.dump({"epoch": epoch, **{k: str(v) for k, v in val_m.items()}}, f, indent=2)
            print(f"  ✓ Student saved  val_f1={best_f1:.4f}")

    return student, best_f1


def main():
    set_seed(SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    train_loader, val_loader, test_loader = build_dataloaders()

    teacher, best_teacher_f1 = phase1_teacher(train_loader, val_loader, device)

    print("\n--- Teacher final eval ---")
    torch.cuda.empty_cache()
    print_metrics("Teacher Val ",  evaluate_teacher(teacher, val_loader,  device, split="Val"))
    torch.cuda.empty_cache()
    print_metrics("Teacher Test",  evaluate_teacher(teacher, test_loader, device, split="Test"))

    student, best_student_f1 = phase2_student(teacher, train_loader, val_loader, device)

    print("\n" + "=" * 60 + "\nFinal Test Evaluation\n" + "=" * 60)
    torch.cuda.empty_cache()
    student.load_state_dict(load_file(os.path.join(SAVE_DIR, "student_best.safetensors")))
    test_m = evaluate_student(student, test_loader, device, split="Test")
    print_metrics("Student Test", test_m)

    with open(os.path.join(SAVE_DIR, "test_results.json"), "w") as f:
        json.dump(test_m, f, indent=2)

    print(f"\nDone.")
    print(f"  Teacher best Val F1 = {best_teacher_f1:.4f}")
    print(f"  Student best Val F1 = {best_student_f1:.4f}")


if __name__ == "__main__":
    main()
