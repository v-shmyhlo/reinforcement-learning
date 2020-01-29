import argparse

import gym
import gym.wrappers
import numpy as np
import torch
import torch.nn as nn
import torch.optim
import torch.optim
from all_the_tools.metrics import Mean, Last, FPS
from all_the_tools.torch.utils import seed_torch
from tensorboardX import SummaryWriter
from tqdm import tqdm

import wrappers
from algorithms.common import build_optimizer, build_transform
from algorithms2.rollout import Rollout
from config import build_default_config
from model import Model
from utils import n_step_discounted_return
from vec_env import VecEnv

DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')


# TODO: finite horizon undiscounted
# TODO: torch wrapper
# TODO: revisit stat calculation
# TODO: shared weights
# TODO: normalize advantage?
# TODO: normalize input (especially images)


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment-path', type=str, default='./tf_log/pg-mc')
    parser.add_argument('--config-path', type=str, required=True)
    parser.add_argument('--monitor', action='store_true')

    return parser


def main():
    def on_rollout_ready(rollout):
        dist, values = model(rollout.states)
        _, value_prime = model(rollout.state_prime)
        value_prime = value_prime.detach()
        returns = n_step_discounted_return(rollout.rewards, value_prime, rollout.dones, gamma=config.gamma)

        # critic
        errors = returns - values
        critic_loss = errors**2

        # actor
        advantages = errors.detach()
        actor_loss = -(dist.log_prob(rollout.actions) * advantages)
        actor_loss -= config.entropy_weight * dist.entropy()

        loss = (actor_loss + critic_loss).sum(1)

        metrics['loss'].update(loss.data.cpu().numpy())
        metrics['lr'].update(np.squeeze(scheduler.get_lr()))
        metrics['step/entropy'].update(dist.entropy().data.cpu().numpy())

        # training
        optimizer.zero_grad()
        loss.mean().backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.)
        optimizer.step()

        metrics['histograms']['step/action'].update(rollout.actions.data.cpu().numpy())
        metrics['histograms']['step/reward'].update(rollout.rewards.data.cpu().numpy())
        metrics['histograms']['step/return'].update(returns.data.cpu().numpy())
        metrics['histograms']['step/value'].update(values.data.cpu().numpy())
        metrics['histograms']['step/advantage'].update(advantages.data.cpu().numpy())

    args = build_parser().parse_args()
    config = build_default_config()
    config.merge_from_file(args.config_path)
    config.experiment_path = args.experiment_path
    config.freeze()
    del args

    seed_torch(config.seed)
    env = wrappers.Torch(
        VecEnv([
            lambda: gym.wrappers.TransformObservation(
                gym.make(config.env),
                build_transform(config.transform))
            for _ in range(config.workers)]),
        device=DEVICE)
    env.seed(config.seed)
    writer = SummaryWriter(config.experiment_path)

    # if args.monitor:
    #     env = gym.wrappers.Monitor(env, os.path.join('./data', config.env), force=True)

    model = Model(config.model, env.observation_space, env.action_space)
    model = model.to(DEVICE)
    optimizer = build_optimizer(config.opt, model.parameters())
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, config.episodes)

    metrics = {
        'scalars': {
            'loss': Mean(),
            'lr': Last(),
            'eps': FPS(),
            'ep/length': Mean(),
            'ep/reward': Mean(),
            'step/entropy': Mean(),
        },
        'histograms': {
            'step/action': Last(),
            'step/reward': Last(),
            'step/return': Last(),
            'step/value': Last(),
            'step/advantage': Last(),
        }
    }

    # ==================================================================================================================
    # training loop
    model.train()
    episode = 0
    ep_length = torch.zeros(config.workers, device=DEVICE)
    ep_reward = torch.zeros(config.workers, device=DEVICE)
    s = env.reset()

    bar = tqdm(total=config.episodes, desc='training')
    history = []
    frames = []
    while episode < config.episodes:
        with torch.no_grad():
            if frames is not None:
                frame = torch.tensor(env.render(mode='rgb_array')).permute(2, 0, 1)
                frames.append(frame)

            a, _ = model(s.float())
            a = a.sample()
            s_prime, r, d, _ = env.step(a)
            ep_length += 1
            ep_reward += r
            history.append((s.float(), a, r, d))
            s = s_prime

        if len(history) == config.horizon:
            rollout = Rollout.build(history, s_prime.float())  # TODO: s or s_prime?
            history = []
            on_rollout_ready(rollout)

        indices, = torch.where(d)
        for i in indices:
            metrics['eps'].update(1)
            metrics['ep/length'].update(ep_length[i].data.cpu().numpy())
            metrics['ep/reward'].update(ep_reward[i].data.cpu().numpy())
            ep_length[i] = 0
            ep_reward[i] = 0
            episode += 1
            scheduler.step()
            bar.update(1)

            if episode % config.log_interval == 0 and episode > 0:
                for k in metrics['scalars']:
                    writer.add_scalar(k, metrics['scalars'][k].compute_and_reset(), global_step=episode)
                for k in metrics['histograms']:
                    writer.add_histogram(k, metrics['histograms'][k].compute_and_reset(), global_step=episode)

            if i == 0:
                if frames is not None:
                    writer.add_video(
                        'episode', torch.stack(frames, 0).unsqueeze(0), fps=24, global_step=episode)
                frames = []

    bar.close()
    env.close()


if __name__ == '__main__':
    main()
