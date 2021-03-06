import gym


# TODO: what to do with render?
# TODO: handle episode end


class SkipObs(gym.Wrapper):
    def __init__(self, env, k):
        super().__init__(env)

        self.k = k

    def step(self, action):
        reward_buffer = 0
        for _ in range(self.k):
            obs, reward, done, info = self.env.step(action)
            reward_buffer += reward

            if done:
                break

        return obs, reward_buffer, done, info
