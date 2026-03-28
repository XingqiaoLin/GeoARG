import contextlib
import warnings

import torch
import torch.nn as nn
import torch.nn.functional as F
import esm as esm_lib



class EGNNLayer(nn.Module):
    """
    单层 E(n)-等变消息传递（Satorras et al., ICML 2021）。

    等变原理：
      - 消息 m_ij 只依赖 ||x_i - x_j||²（纯标量）→ 旋转/平移/镜像不变
      - 坐标更新 Δx_i = Σ_j (x_i-x_j)/dist · φ_x(m_ij) → E(3) 等变
    """

    def __init__(self, node_dim: int, hidden_dim: int):
        super().__init__()
        act = nn.SiLU

        # φ_e: [h_i || h_j || sq_dist || plddt_j] → m_ij
        self.edge_mlp = nn.Sequential(
            nn.Linear(node_dim * 2 + 1 + 1, hidden_dim),
            act(),
            nn.Linear(hidden_dim, hidden_dim),
            act(),
        )

        # φ_x: m_ij → 坐标更新标量权重
        self.coord_mlp = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            act(),
            nn.Linear(hidden_dim // 2, 1),
        )

        # φ_h: [h_i || 聚合消息] → 新节点特征
        self.node_mlp = nn.Sequential(
            nn.Linear(node_dim + hidden_dim, hidden_dim),
            act(),
            nn.Linear(hidden_dim, node_dim),
        )

        self.norm = nn.LayerNorm(node_dim)

    def forward(
        self,
        h: torch.Tensor,           # [N, node_dim]
        x: torch.Tensor,           # [N, 3]  Cα 坐标
        edge_index: torch.Tensor,  # [2, E]
        plddt: torch.Tensor,       # [N]
    ):
        src, dst = edge_index[0], edge_index[1]

        # 边消息
        delta   = x[src] - x[dst]                              # [E, 3]
        sq_dist = (delta ** 2).sum(dim=-1, keepdim=True)       # [E, 1]
        plddt_j = plddt[dst].clamp(min=1e-6).unsqueeze(-1)     # [E, 1]

        m_ij = self.edge_mlp(
            torch.cat([h[src], h[dst], sq_dist, plddt_j], dim=-1)
        )  # [E, hidden_dim]

        # plddt 归一化权重
        raw_w = plddt[dst].clamp(min=1e-6)
        w_sum = torch.zeros(h.size(0), device=h.device)
        w_sum.scatter_add_(0, dst, raw_w)
        w = raw_w / (w_sum[dst] + 1e-8)                        # [E]

        # 坐标更新（等变）
        coord_w  = self.coord_mlp(m_ij)                        # [E, 1]
        unit_dir = delta / (sq_dist.sqrt() + 1e-8)             # [E, 3]
        coord_agg = torch.zeros_like(x)
        coord_agg.scatter_add_(
            0,
            dst.unsqueeze(-1).expand(-1, 3),
            unit_dir * coord_w * w.unsqueeze(-1),
        )
        x_new = x + coord_agg

        # 节点特征更新（不变）
        feat_agg = torch.zeros(h.size(0), m_ij.size(-1), device=h.device)
        feat_agg.scatter_add_(
            0,
            dst.unsqueeze(-1).expand_as(m_ij),
            m_ij * w.unsqueeze(-1),
        )
        h_new = self.norm(h + self.node_mlp(torch.cat([h, feat_agg], dim=-1)))

        return h_new, x_new


class E3GNN(nn.Module):
    """
    多层 EGNN。

    接口变化（相对于原 SE3GNN）：
      - 去掉 edge_in 参数（不再需要预计算的 edge_feat）
      - forward 签名改为 (node_feat, coords, edge_index, plddt)
      - 返回值不变：(z_per_residue [N, out_dim], z_global [out_dim])
    """

    def __init__(
        self,
        node_in:  int = 27,
        hidden:   int = 512,
        out_dim:  int = 512,
        n_layers: int = 6,
    ):
        super().__init__()
        self.input_proj  = nn.Linear(node_in, hidden)
        self.layers      = nn.ModuleList(
            [EGNNLayer(hidden, hidden) for _ in range(n_layers)]
        )
        self.output_proj = nn.Linear(hidden, out_dim)

    def forward(
        self,
        node_feat:  torch.Tensor,   # [N, node_in]
        coords:     torch.Tensor,   # [N, 3]  真实 Cα 坐标
        edge_index: torch.Tensor,   # [2, E]
        plddt:      torch.Tensor,   # [N]
    ):
        h = self.input_proj(node_feat)
        x = coords.clone()
        for layer in self.layers:
            h, x = layer(h, x, edge_index, plddt)
        z_per_residue = self.output_proj(h)
        return z_per_residue, z_per_residue.mean(0)




class ESM2Encoder(nn.Module):
    def __init__(self, proj_dim: int = 512, freeze_esm: bool = True, unfreeze_last_n: int = 0):
        super().__init__()
        self.esm_model, self.alphabet = esm_lib.pretrained.esm2_t33_650M_UR50D()
        self.batch_converter = self.alphabet.get_batch_converter()

        for p in self.esm_model.parameters():
            p.requires_grad_(False)

        if unfreeze_last_n > 0:
            total = len(self.esm_model.layers)
            for i, layer in enumerate(self.esm_model.layers):
                if i >= total - unfreeze_last_n:
                    for p in layer.parameters():
                        p.requires_grad_(True)
            for p in self.esm_model.emb_layer_norm_after.parameters():
                p.requires_grad_(True)
            n_trainable = sum(p.numel() for p in self.esm_model.parameters() if p.requires_grad)
            print(f"ESM2 partial finetune: last {unfreeze_last_n} layers, {n_trainable/1e6:.1f}M trainable params")

        self.proj = nn.Sequential(nn.Linear(1280, proj_dim), nn.ReLU())

    def forward(self, sequences: list[str], device):
        data = [(f"seq{i}", s) for i, s in enumerate(sequences)]
        _, _, tokens = self.batch_converter(data)
        tokens = tokens.to(device)

        has_trainable = any(p.requires_grad for p in self.esm_model.parameters())
        ctx = contextlib.nullcontext() if (self.esm_model.training and has_trainable) \
              else torch.no_grad()

        with ctx:
            results = self.esm_model(tokens, repr_layers=[33], return_contacts=False)

        token_repr = results["representations"][33]
        return [self.proj(token_repr[i, 1:len(seq) + 1, :].float()) for i, seq in enumerate(sequences)]



class CrossAttentionFusion(nn.Module):
    def __init__(self, dim: int = 512, n_heads: int = 8):
        super().__init__()
        self.attn  = nn.MultiheadAttention(embed_dim=dim, num_heads=n_heads, batch_first=True)
        self.norm  = nn.LayerNorm(dim)
        self.ffn   = nn.Sequential(nn.Linear(dim, dim * 2), nn.ReLU(), nn.Linear(dim * 2, dim))
        self.norm2 = nn.LayerNorm(dim)

    def _align(self, z_struc, L: int):
        N = z_struc.size(0)
        if N == L:
            return z_struc
        if N > L:
            # parse_pdb_to_graph 里已做 residues[:MAX_SEQ_LEN]，正常不会触发
            warnings.warn(f"_align: struct nodes ({N}) > seq len ({L}), truncating.")
            return z_struc[:L]
        pad = torch.zeros(L - N, z_struc.size(1), device=z_struc.device)
        return torch.cat([z_struc, pad], dim=0)

    def forward(self, z_seq, z_struc_per_res):
        L  = z_seq.size(0)
        kv = self._align(z_struc_per_res, L)
        Q  = z_seq.unsqueeze(0)
        K  = kv.unsqueeze(0)
        attn_out, _ = self.attn(Q, K, K)
        attn_out = attn_out.squeeze(0)
        x = self.norm(z_seq + attn_out)
        x = self.norm2(x + self.ffn(x))
        return x.mean(0)


class ClassificationHead(nn.Module):
    def __init__(self, in_dim: int = 512, num_classes: int = 2, dropout: float = 0.1):
        super().__init__()
        self.head = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(in_dim, in_dim // 2), nn.ReLU(),
            nn.Linear(in_dim // 2, num_classes),
        )

    def forward(self, z):
        return self.head(z)



class GeoARGTeacher(nn.Module):
    def __init__(
        self,
        num_classes:     int  = 2,
        proj_dim:        int  = 512,
        freeze_esm:      bool = True,
        unfreeze_last_n: int  = 4,
    ):
        super().__init__()
        self.esm_enc = ESM2Encoder(proj_dim=proj_dim, freeze_esm=freeze_esm,
                                    unfreeze_last_n=unfreeze_last_n)
        self.gnn     = E3GNN(node_in=27, hidden=512, out_dim=512, n_layers=6)
        self.fusion  = CrossAttentionFusion(dim=512, n_heads=8)
        self.head    = ClassificationHead(in_dim=512, num_classes=num_classes)

    def forward(self, sequences, graph_data, device):
        z_seq = self.esm_enc(sequences, device)[0]

        # coords 是 parse_pdb_to_graph 新增的字段
        z_per_res, _ = self.gnn(
            graph_data["node_feat"].to(device),
            graph_data["coords"].to(device),       # ← E3GNN 新增
            graph_data["edge_index"].to(device),
            graph_data["plddt"].to(device),
        )
        z_fusion = self.fusion(z_seq, z_per_res)
        return self.head(z_fusion), z_fusion


class ESM2StudentEncoder(nn.Module):
    def __init__(self, proj_dim: int = 512):
        super().__init__()
        self.esm_model, self.alphabet = esm_lib.pretrained.esm2_t12_35M_UR50D()
        self.batch_converter = self.alphabet.get_batch_converter()
        self.proj = nn.Sequential(nn.Linear(480, proj_dim), nn.ReLU())

    def forward(self, sequences: list[str], device):
        data = [(f"seq{i}", s) for i, s in enumerate(sequences)]
        _, _, tokens = self.batch_converter(data)
        tokens  = tokens.to(device)
        results = self.esm_model(tokens, repr_layers=[12], return_contacts=False)
        token_repr = results["representations"][12]
        return [self.proj(token_repr[i, 1:len(seq) + 1, :]) for i, seq in enumerate(sequences)]


class GeoARGStudent(nn.Module):
    def __init__(self, num_classes: int = 2, proj_dim: int = 512):
        super().__init__()
        self.esm_enc = ESM2StudentEncoder(proj_dim=proj_dim)
        self.head    = ClassificationHead(in_dim=proj_dim, num_classes=num_classes)

    def forward(self, sequences, device):
        z = self.esm_enc(sequences, device)[0].mean(0)
        return self.head(z), z



class DistillationLoss(nn.Module):
    def __init__(self, lambda1: float = 1.0, lambda2: float = 0.1, temperature: float = 4.0):
        super().__init__()
        self.lambda1 = lambda1
        self.lambda2 = lambda2
        self.T       = temperature
        self.ce      = nn.CrossEntropyLoss()
        self.mse     = nn.MSELoss()

    def forward(self, s_logits, t_logits, z_student, z_teacher, label):
        l_task   = self.ce(s_logits.unsqueeze(0), label.unsqueeze(0))
        l_logits = F.kl_div(
            F.log_softmax(s_logits / self.T, dim=-1),
            F.softmax(t_logits / self.T, dim=-1),
            reduction="batchmean",
        ) * (self.T ** 2)
        l_fusion = self.mse(z_student, z_teacher.detach())
        total    = l_task + self.lambda1 * l_logits + self.lambda2 * l_fusion
        return total, {
            "l_task":   l_task.item(),
            "l_logits": l_logits.item(),
            "l_fusion": l_fusion.item(),
            "total":    total.item(),
        }
