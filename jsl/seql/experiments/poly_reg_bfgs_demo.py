import jax.numpy as jnp
from jax import random

from functools import partial

from jsl.seql.agents.bfgs_agent import bfgs_agent
from jsl.seql.environments.base import make_evenly_spaced_x_sampler, make_random_poly_regression_environment
from jsl.seql.experiments.plotting import plot_posterior_predictive
from jsl.seql.utils import train


belief = None


def penalized_objective_fn(params, x, y, model_fn, strength=0.):
    tmp = y - model_fn(params, x)
    return jnp.sum(tmp.T @ tmp) + strength * jnp.sum(params**2)

def callback_fn(env, obs_noise, timesteps, **kwargs):
    global belief
    belief = kwargs["belief_state"]
    mu, sigma = belief.x, None
    filename = "poly_reg_bfgs_ppd"

    plot_posterior_predictive(env,
                              mu,
                              sigma,
                              obs_noise,
                              timesteps,
                              filename,
                              **kwargs)


def main():

    key = random.PRNGKey(0)
    degree = 3
    ntrain = 200  # 80% of the data
    ntest = 50  # 20% of the data
    
    min_val, max_val = -3, 3
    x_test_generator = make_evenly_spaced_x_sampler(max_val,
                                                    use_bias=False,
                                                    min_val=min_val)

    env = make_random_poly_regression_environment(key,
                                                  degree,
                                                  ntrain,
                                                  ntest,
                                                  x_test_generator=x_test_generator)
                                                    
    buffer_size = 1
    obs_noise, tau = 0.01, 1.
    strength = obs_noise / tau

    partial_objective_fn = partial(penalized_objective_fn, strength=strength)

    agent = bfgs_agent(partial_objective_fn,
                        obs_noise=obs_noise,
                        buffer_size=buffer_size)


    nfeatures = degree + 1
    params = jnp.zeros((nfeatures,))

    belief = agent.init_state(params)

    timesteps = [5, 10, 15]
    partial_callback = lambda **kwargs: callback_fn(env, obs_noise, timesteps, **kwargs)

    nsteps = 20
    _, unused_rewards = train(belief,
                              agent,
                              env,
                              nsteps=nsteps,
                              callback=partial_callback)

if __name__ == "__main__":
    main()