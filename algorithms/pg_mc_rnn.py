import itertools
import os

import gym
import gym.wrappers
import numpy as np
import torch
from all_the_tools.metrics import Mean
from all_the_tools.torch.utils import seed_torch
from tensorboardX import SummaryWriter
from tqdm import tqdm

import utils
from algorithms.common import build_optimizer
from model import ModelRNN
from utils import total_discounted_return

# TODO: train/eval
# TODO: bn update
# TODO: return normalization
# TODO: normalize advantage?

DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')


def build_batch(history):
    states, actions, rewards = zip(*history)

    states = torch.tensor(states, dtype=torch.float, device=DEVICE).transpose(0, 1)
    actions = torch.tensor(actions, dtype=torch.long, device=DEVICE).transpose(0, 1)
    rewards = torch.tensor(rewards, dtype=torch.float, device=DEVICE).transpose(0, 1)

    return states, actions, rewards


def build_parser():
    parser = utils.ArgumentParser()
    parser.add_argument('--learning-rate', type=float, default=1e-3)
    parser.add_argument('--optimizer', type=str, choices=['momentum', 'rmsprop', 'adam'], default='adam')
    parser.add_argument('--experiment-path', type=str, default='./tf_log/pg-mc-rnn')
    parser.add_argument('--env', type=str, required=True)
    parser.add_argument('--episodes', type=int, default=10000)
    parser.add_argument('--entropy-weight', type=float, default=1e-3)
    parser.add_argument('--gamma', type=float, default=0.99)
    parser.add_argument('--monitor', action='store_true')

    return parser


def main():
    args = build_parser().parse_args()
    seed_torch(args.seed)
    env = gym.make(args.env)
    env.seed(args.seed)
    writer = SummaryWriter(args.experiment_path)

    if args.monitor:
        env = gym.wrappers.Monitor(env, os.path.join('./data', args.env), force=True)

    model = ModelRNN(np.squeeze(env.observation_space.shape), env.action_space.n)
    model = model.to(DEVICE)
    optimizer = build_optimizer(args.optimizer, model.parameters(), args.learning_rate)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, args.episodes)

    metrics = {
        'loss': Mean(),
        'ep_length': Mean(),
        'ep_reward': Mean(),
    }

    # ==================================================================================================================
    # training loop
    model.train()
    for episode in tqdm(range(args.episodes), desc='training'):
        history = []
        s = env.reset()
        h = None
        ep_reward = 0

        with torch.no_grad():
            for ep_length in itertools.count():
                a, h = model.policy(torch.tensor(s, dtype=torch.float, device=DEVICE), h)
                a = a.sample().item()
                s_prime, r, d, _ = env.step(a)
                ep_reward += r
                history.append(([s], [a], [r]))

                if d:
                    break
                else:
                    s = s_prime

        states, actions, rewards = build_batch(history)

        # actor
        dist, _ = model.policy(states, None)
        returns = total_discounted_return(rewards, gamma=args.gamma)
        advantages = returns.detach()
        actor_loss = -(dist.log_prob(actions) * advantages)
        actor_loss -= args.entropy_weight * dist.entropy()

        loss = actor_loss.sum(1)

        # training
        optimizer.zero_grad()
        loss.mean().backward()
        optimizer.step()
        scheduler.step()

        metrics['loss'].update(loss.data.cpu().numpy())
        metrics['ep_length'].update(ep_length)
        metrics['ep_reward'].update(ep_reward)

        if episode % 100 == 0:
            for k in metrics:
                writer.add_scalar(k, metrics[k].compute_and_reset(), global_step=episode)
            writer.add_histogram('return', returns, global_step=episode)
            writer.add_histogram('advantage', advantages, global_step=episode)


if __name__ == '__main__':
    main()
