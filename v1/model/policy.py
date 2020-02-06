import numpy as np
import torch.distributions
import torch.nn.functional as F
from torch import nn as nn


class PolicyCategorical(nn.Module):
    def __init__(self, in_features, action_space):
        super().__init__()

        self.layers = nn.Linear(in_features, action_space.n)

    def forward(self, input):
        input = self.layers(input)
        dist = torch.distributions.Categorical(logits=input)

        return dist


class PolicyBeta(nn.Module):
    def __init__(self, in_features, action_space):
        super().__init__()

        assert np.array_equal(action_space.low, np.zeros_like(action_space.low))
        assert np.array_equal(action_space.high, np.ones_like(action_space.high))

        self.layers = nn.Linear(in_features, np.prod(action_space.shape) * 2)

    def forward(self, input):
        input = self.layers(input)
        input = F.softplus(input) + 1.

        a, b = torch.split(input, input.size(-1) // 2, -1)
        dist = torch.distributions.Beta(a, b)

        return dist