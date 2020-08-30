from all_the_tools.config import Config as C

config = C(
    seed=42,
    env='MiniGrid-FourRooms-v0',
    episodes=100000,
    log_interval=1000,
    transforms=[
        C(type='gridworld'),
    ],
    gamma=0.99,
    entropy_weight=1e-2,
    adv_norm=True,  # be sure to have large batch size (workers * horizon)
    horizon=32,
    workers=32,
    model=C(
        encoder=C(
            type='gridworld',
            base_channels=8,
            out_features=32,
            shared=True),
        rnn=C(
            type='lstm')),
    opt=C(
        type='adam',
        lr=1e-3))
