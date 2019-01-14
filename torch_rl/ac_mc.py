import utils
from ticpfptp.metrics import Mean
from ticpfptp.format import args_to_string
from ticpfptp.torch import fix_seed
import numpy as np
import gym
import os
from tensorboardX import SummaryWriter
import torch
import itertools
from tqdm import tqdm
from torch_rl.network import PolicyCategorical, ValueFunction
from torch_rl.utils import batch_return


# TODO: train/eval
# TODO: bn update
# TODO: return normalization
# TODO: monitored session
# TODO: normalize advantage?


def build_batch(history):
    states, actions, rewards = zip(*history)

    states = torch.tensor(states).transpose(0, 1).float()
    actions = torch.tensor(actions).transpose(0, 1)
    rewards = torch.tensor(rewards).transpose(0, 1)

    return states, actions, rewards


def build_optimizer(optimizer, parameters, learning_rate):
    if optimizer == 'adam':
        return torch.optim.Adam(parameters, learning_rate, weight_decay=1e-4)
    elif optimizer == 'momentum':
        return torch.optim.SGD(parameters, learning_rate, momentum=0.9, weight_decay=1e-4)
    else:
        raise AssertionError('invalid optimizer {}'.format(optimizer))


def build_parser():
    parser = utils.ArgumentParser()
    parser.add_argument('--learning-rate', type=float, default=1e-3)
    parser.add_argument('--optimizer', type=str, choices=['adam', 'momentum'], default='adam')
    parser.add_argument('--experiment-path', type=str, default='./tf_log/torch/pg-mc')
    parser.add_argument('--env', type=str, required=True)
    parser.add_argument('--episodes', type=int, default=10000)
    parser.add_argument('--entropy-weight', type=float, default=1e-2)
    parser.add_argument('--gamma', type=float, default=0.99)
    parser.add_argument('--monitor', action='store_true')

    return parser


def main():
    args = build_parser().parse_args()
    print(args_to_string(args))
    fix_seed(args.seed)
    experiment_path = os.path.join(args.experiment_path, args.env)
    env = gym.make(args.env)
    env.seed(args.seed)
    writer = SummaryWriter(experiment_path)

    if args.monitor:
        env = gym.wrappers.Monitor(env, os.path.join('./data', args.env), force=True)

    value_function = ValueFunction(np.squeeze(env.observation_space.shape))
    policy = PolicyCategorical(np.squeeze(env.observation_space.shape), np.squeeze(env.action_space.shape))
    optimizer = build_optimizer(
        args.optimizer, list(value_function.parameters()) + list(policy.parameters()), args.learning_rate)
    metrics = {'loss': Mean(), 'ep_length': Mean(), 'ep_reward': Mean()}

    if os.path.exists(os.path.join(experiment_path, 'parameters')):
        policy.load_state_dict(torch.load(os.path.join(experiment_path, 'parameters')))

    policy.train()
    for step in tqdm(range(args.episodes), desc='training'):
        history = []
        s = env.reset()
        ep_reward = 0

        for t in itertools.count():
            a = policy(torch.tensor(s).float()).sample().item()
            s_prime, r, d, _ = env.step(a)
            ep_reward += r

            history.append(([s], [a], [r]))

            if d:
                break
            else:
                s = s_prime

        states, actions, rewards = build_batch(history)

        # critic
        values = value_function(states)
        returns = batch_return(rewards, gamma=args.gamma)
        errors = returns - values
        critic_loss = (errors**2).mean()

        # actor
        dist = policy(states)
        advantages = errors.detach()
        actor_loss = -(dist.log_prob(actions) * advantages).mean()
        actor_loss -= args.entropy_weight * torch.mean(dist.entropy())

        # training
        loss = actor_loss + 0.5 * critic_loss

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        metrics['loss'].update(loss.data.cpu().numpy())
        metrics['ep_length'].update(t)
        metrics['ep_reward'].update(ep_reward)

        if step % 100 == 0:
            for k in metrics:
                writer.add_scalar(k, metrics[k].compute_and_reset(), global_step=step)


if __name__ == '__main__':
    main()
