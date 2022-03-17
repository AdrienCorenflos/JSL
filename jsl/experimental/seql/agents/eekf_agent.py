# EEKF agent
from jax import vmap

import chex
from typing import List

from jsl.experimental.seql.agents.base import Agent
from jsl.nlds.base import NLDS
from jsl.nlds.extended_kalman_filter import filter
from jsl.experimental.seql.agents.kf_agent import BeliefState, Info
from jsl.experimental.seql.utils import posterior_noise

def eekf(nlds: NLDS,
         return_params: List[str] = ["mean", "cov"],
         return_history: bool = False,
         obs_noise: float = 1.):

    def init_state(mu: chex.Array,
                   Sigma: chex.Array):
        return BeliefState(mu, Sigma)

    def update(belief: BeliefState,
               x: chex.Array,
               y: chex.Array):
        (mu, Sigma), history = filter(nlds, belief.mu,
                                      y, x, belief.Sigma,
                                      return_params,
                                      return_history=return_history)
        if return_history:
            return BeliefState(mu, Sigma), Info(history["mean"], history["cov"])
        
        return BeliefState(mu, Sigma), Info()

    def predict(belief: BeliefState,
                x: chex.Array):
        v_posterior_noise = vmap(posterior_noise, in_axes=(0, None, None))
        noise = v_posterior_noise(x, belief.Sigma, obs_noise)
        return x @ belief.mu, noise
        
    return Agent(init_state, update, predict)