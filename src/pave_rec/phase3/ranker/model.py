"""PyTorch SASRec implementation loaded only by the optional training path."""

from __future__ import annotations

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from .config import SasrecModelConfig


class SasrecModel(nn.Module):
    def __init__(self, *, vocabulary_size: int, config: SasrecModelConfig) -> None:
        super().__init__()
        if vocabulary_size <= 0:
            raise ValueError("SASRec vocabulary must not be empty")
        self.vocabulary_size = vocabulary_size
        self.config = config
        self.item_embedding = nn.Embedding(
            vocabulary_size + 1,
            config.hidden_size,
            padding_idx=config.pad_index,
        )
        self.position_embedding = nn.Embedding(
            config.max_history_length,
            config.hidden_size,
        )
        self.input_dropout = nn.Dropout(config.dropout)
        self.blocks = nn.ModuleList(
            nn.TransformerEncoderLayer(
                d_model=config.hidden_size,
                nhead=config.attention_head_count,
                dim_feedforward=config.feed_forward_size,
                dropout=config.dropout,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            for _ in range(config.block_count)
        )
        self.final_norm = nn.LayerNorm(config.hidden_size)
        causal_mask = torch.triu(
            torch.ones(
                config.max_history_length,
                config.max_history_length,
                dtype=torch.bool,
            ),
            diagonal=1,
        )
        self.register_buffer("causal_mask", causal_mask, persistent=False)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for name, parameter in self.named_parameters():
            if name.endswith("bias"):
                nn.init.zeros_(parameter)
            elif name.endswith("weight") and parameter.ndim == 1:
                nn.init.ones_(parameter)
            else:
                nn.init.normal_(parameter, mean=0.0, std=self.config.initializer_std)
        self.zero_pad_embedding()

    def zero_pad_embedding(self) -> None:
        with torch.no_grad():
            self.item_embedding.weight[self.config.pad_index].zero_()

    def encode(self, item_indices: Tensor) -> Tensor:
        if item_indices.ndim != 2:
            raise ValueError("SASRec input must have shape [batch, sequence]")
        if item_indices.shape[1] != self.config.max_history_length:
            raise ValueError("SASRec input sequence length does not match the model recipe")
        if item_indices.dtype != torch.long:
            raise ValueError("SASRec input indices must use torch.long")
        if torch.any(item_indices < 0) or torch.any(item_indices > self.vocabulary_size):
            raise ValueError("SASRec input index is outside the exact vocabulary")
        padding_mask = item_indices.eq(self.config.pad_index)
        if torch.any(padding_mask.all(dim=1)):
            raise ValueError("SASRec requires at least one known history item")
        positions = torch.arange(
            item_indices.shape[1],
            device=item_indices.device,
            dtype=torch.long,
        ).unsqueeze(0)
        hidden = self.item_embedding(item_indices) + self.position_embedding(positions)
        hidden = self.input_dropout(hidden)
        hidden = hidden.masked_fill(padding_mask.unsqueeze(-1), 0.0)
        mask = self.causal_mask[: item_indices.shape[1], : item_indices.shape[1]]
        for block in self.blocks:
            hidden = block(hidden, src_mask=mask, src_key_padding_mask=padding_mask)
            hidden = hidden.masked_fill(padding_mask.unsqueeze(-1), 0.0)
        hidden = self.final_norm(hidden)
        hidden = hidden.masked_fill(padding_mask.unsqueeze(-1), 0.0)
        position_grid = torch.arange(item_indices.shape[1], device=item_indices.device)
        last_positions = position_grid.unsqueeze(0).masked_fill(padding_mask, -1).max(dim=1).values
        batch_indices = torch.arange(item_indices.shape[0], device=item_indices.device)
        return hidden[batch_indices, last_positions]

    def score_items(self, sequence_features: Tensor, item_indices: Tensor) -> Tensor:
        if sequence_features.ndim != 2 or item_indices.ndim != 1:
            raise ValueError("invalid SASRec scoring tensor shapes")
        embeddings = self.item_embedding(item_indices)
        return sequence_features @ embeddings.transpose(0, 1)

    def sampled_binary_loss(
        self,
        history_indices: Tensor,
        positive_indices: Tensor,
        negative_indices: Tensor,
    ) -> Tensor:
        features = self.encode(history_indices)
        positive_logits = (features * self.item_embedding(positive_indices)).sum(dim=-1)
        negative_logits = (features * self.item_embedding(negative_indices)).sum(dim=-1)
        return -(F.logsigmoid(positive_logits) + F.logsigmoid(-negative_logits)).mean()
