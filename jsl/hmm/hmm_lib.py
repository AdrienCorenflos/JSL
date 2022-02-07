# Inference and learning code for Hidden Markov Models using discrete observations.
# Has Numpy and Jax versions of each function.
# The Jax version of inference (not learning)
# has been upstreamed to https://github.com/deepmind/distrax/blob/master/distrax/_src/utils/hmm.py.
# This version is kept for historical purposes.
# Author: Gerardo Duran-Martin (@gerdm), Aleyna Kara (@karalleyna), Kevin Murphy (@murphyk)


import jax
import numpy as np
import jax.numpy as jnp
from dataclasses import dataclass
from numpy.random import seed
from jax import lax, vmap, jit
from jax.scipy.special import logit
from functools import partial

import jax
import numpy as np
import jax.numpy as jnp
from scipy.special import softmax
from jax import vmap
from jax.ops import index_update, index
from jax.random import PRNGKey
from dataclasses import dataclass

import jax
import itertools
from jax import jit
from jax.nn import softmax
from jax.random import PRNGKey, split, normal
from jsl.hmm.hmm_utils import hmm_sample_minibatches

import superimport
#!pip install flax
import flax

'''
Hidden Markov Model class used in numpy implementations of inference algorithms.
'''
@dataclass
class HMMNumpy:
   trans_mat: np.array # A : (n_states, n_states)
   obs_mat: np.array # B : (n_states, n_obs)
   init_dist: np.array # pi : (n_states)

'''
Hidden Markov Model class used in jax implementations of inference algorithms.

The functions of optimizers expect that the type of its parameters 
is pytree. So, they cannot work on a vanilla dataclass. To see more:
                https://github.com/google/jax/issues/2371

Since the flax.dataclass is registered pytree beforehand, it facilitates to use
jit, vmap and optimizers on the hidden markov model.
'''
@flax.struct.dataclass
class HMMJax:
   trans_mat: jnp.array # A : (n_states, n_states)
   obs_mat: jnp.array # B : (n_states, n_obs)
   init_dist: jnp.array # pi : (n_states)

def normalize_numpy(u, axis=0, eps=1e-15):
    '''
    Normalizes the values within the axis in a way that they sum up to 1.

    Parameters
    ----------
    u : array
    axis : int
    eps : float
        Threshold for the alpha values

    Returns
    -------
    * array
        Normalized version of the given matrix

    * array(seq_len, n_hidden) :
        The values of the normalizer
    '''
    u = np.where(u == 0, 0, np.where(u < eps, eps, u))
    c = u.sum(axis=axis)
    c = np.where(c == 0, 1, c)
    return u / c, c

def normalize(u, axis=0, eps=1e-15):
    '''
    Normalizes the values within the axis in a way that they sum up to 1.

    Parameters
    ----------
    u : array
    axis : int
    eps : float
        Threshold for the alpha values

    Returns
    -------
    * array
        Normalized version of the given matrix

    * array(seq_len, n_hidden) :
        The values of the normalizer
    '''
    u = jnp.where(u == 0, 0, jnp.where(u < eps, eps, u))
    c = u.sum(axis=axis)
    c = jnp.where(c == 0, 1, c)
    return u / c, c

def hmm_sample_numpy(params, seq_len, random_state=0):
    '''
    Samples an observation of given length according to the defined
    hidden markov model and gives the sequence of the hidden states
    as well as the observation.

    Parameters
    ----------
    params : HMMNumpy
        Hidden Markov Model

    seq_len: array(seq_len)
        The length of the observation sequence

    random_state : int
        Seed value

    Returns
    -------
    * array(seq_len,)
        Hidden state sequence

    * array(seq_len,) :
        Observation sequence
    '''
    def sample_one_step_(hist, a, p):
        x_t = np.random.choice(a=a, p=p)
        return np.append(hist, [x_t]), x_t

    seed(random_state)

    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    state_seq = np.array([], dtype=int)
    obs_seq = np.array([], dtype=int)

    latent_states = np.arange(n_states)
    obs_states = np.arange(n_obs)

    state_seq, zt = sample_one_step_(state_seq, latent_states, init_dist)
    obs_seq, xt = sample_one_step_(obs_seq, obs_states, obs_mat[zt])

    for _ in range(1, seq_len):
        state_seq, zt = sample_one_step_(state_seq, latent_states, trans_mat[zt])
        obs_seq, xt = sample_one_step_(obs_seq, obs_states, obs_mat[zt])

    return state_seq, obs_seq

@partial(jit, static_argnums=(1,))
def hmm_sample_jax(params, seq_len, rng_key):
    '''
    Samples an observation of given length according to the defined
    hidden markov model and gives the sequence of the hidden states
    as well as the observation.

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    seq_len: array(seq_len)
        The length of the observation sequence

    rng_key : array
        Random key of shape (2,) and dtype uint32

    Returns
    -------
    * array(seq_len,)
        Hidden state sequence

    * array(seq_len,) :
        Observation sequence
    '''
    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    initial_state = jax.random.categorical(rng_key, logits=logit(init_dist), shape=(1,))
    obs_states = jnp.arange(n_obs)

    def draw_state(prev_state, key):
        logits = logit(trans_mat[:, prev_state])
        state = jax.random.categorical(key, logits=logits.flatten(), shape=(1,))
        return state, state

    rng_key, rng_state, rng_obs = jax.random.split(rng_key, 3)
    keys = jax.random.split(rng_state, seq_len - 1)

    final_state, states = jax.lax.scan(draw_state, initial_state, keys)
    state_seq = jnp.append(jnp.array([initial_state]),states)

    def draw_obs(z, key):
        obs = jax.random.choice(key, a=obs_states, p=obs_mat[z])
        return obs

    keys = jax.random.split(rng_obs, seq_len)
    obs_seq = jax.vmap(draw_obs, in_axes=(0, 0))(state_seq, keys)

    return state_seq, obs_seq


##############################
# Inference

def hmm_forwards_numpy(params, obs_seq, length):
    '''
    Calculates a belief state

    Parameters
    ----------
    params : HMMNumpy
        Hidden Markov Model

    obs_seq: array(seq_len)
        History of observable events

    Returns
    -------
    * float
        The loglikelihood giving log(p(x|model))

    * array(seq_len, n_hidden) :
        All alpha values found for each sample
    '''
    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape
    seq_len = len(obs_seq)

    alpha_hist = np.zeros((seq_len, n_states))
    ll_hist = np.zeros(seq_len)  # loglikelihood history


    alpha_n = init_dist * obs_mat[:, obs_seq[0]]
    alpha_n, cn = normalize_numpy(alpha_n)

    alpha_hist[0] = alpha_n
    ll_hist[0] = np.log(cn)

    for t in range(1, length):
        alpha_n = obs_mat[:, obs_seq[t]] * (alpha_n[:, None] * trans_mat).sum(axis=0)
        alpha_n, cn = normalize_numpy(alpha_n)

        alpha_hist[t] = alpha_n
        ll_hist[t] = np.log(cn) + ll_hist[t-1] # calculates the loglikelihood up to time t

    return ll_hist[length - 1], alpha_hist

@jit
def hmm_forwards_jax(params, obs_seq, length=None):
    '''
    Calculates a belief state

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    obs_seq: array(seq_len)
        History of observable events

    Returns
    -------
    * float
        The loglikelihood giving log(p(x|model))

    * array(seq_len, n_hidden) :
        All alpha values found for each sample
    '''
    seq_len = len(obs_seq)

    if length is None:
        length = seq_len

    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    def scan_fn(carry, t):
        (alpha_prev, log_ll_prev) = carry
        alpha_n = jnp.where(t < length,
                            obs_mat[:, obs_seq[t]] * (alpha_prev[:, None] * trans_mat).sum(axis=0),
                            jnp.zeros_like(alpha_prev))

        alpha_n, cn = normalize(alpha_n)
        carry = (alpha_n, jnp.log(cn) + log_ll_prev)

        return carry, alpha_n

    # initial belief state
    alpha_0, c0 = normalize(init_dist * obs_mat[:, obs_seq[0]])

    # setup scan loop
    init_state = (alpha_0, jnp.log(c0))
    ts = jnp.arange(1, seq_len)
    carry, alpha_hist = lax.scan(scan_fn, init_state, ts)

    # post-process
    alpha_hist = jnp.vstack([alpha_0.reshape(1, n_states), alpha_hist])
    (alpha_final, log_ll) = carry
    return log_ll, alpha_hist

def hmm_loglikelihood_numpy(params, observations, lens):
    '''
    Finds the loglikelihood of each observation sequence sequentially.

    Parameters
    ----------
    params : HMMNumpy
        Hidden Markov Model

    observations: array(N, seq_len)
        Batch of observation sequences

    lens : array(N, seq_len)
        Consists of the valid length of each observation sequence

    Returns
    -------
    * array(N, seq_len)
        Consists of the loglikelihood of each observation sequence
    '''
    return np.array([hmm_forwards_numpy(params, obs, length)[0] for obs, length in zip(observations, lens)])

@jit
def hmm_loglikelihood_jax(params, observations, lens):
    '''
    Finds the loglikelihood of each observation sequence parallel using vmap.

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    observations: array(N, seq_len)
        Batch of observation sequences

    lens : array(N, seq_len)
        Consists of the valid length of each observation sequence

    Returns
    -------
    * array(N, seq_len)
        Consists of the loglikelihood of each observation sequence
    '''
    def forward_(params, x, length):
        return hmm_forwards_jax(params, x, length)[0]

    return vmap(forward_, in_axes=(None, 0, 0))(params, observations, lens)

def hmm_backwards_numpy(params, obs_seq, length=None):
    '''
    Computes the backwards probabilities

    Parameters
    ----------
    params : HMMNumpy
        Hidden Markov Model

    obs_seq: array(seq_len,)
        History of observable events

    length : array(seq_len,)
        The valid length of the observation sequence

    Returns
    -------
    * array(seq_len, n_states)
       Beta values
    '''
    seq_len = len(obs_seq)

    if length is None:
        length = seq_len

    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist

    n_states, n_obs = obs_mat.shape
    beta_next = np.ones(n_states)

    beta_hist = np.zeros((seq_len, n_states))
    beta_hist[-1] = beta_next

    for t in range(2, length + 1):
        beta_next, _ = normalize_numpy((beta_next * obs_mat[:, obs_seq[-t + 1]] * trans_mat).sum(axis=1))
        beta_hist[-t] = beta_next

    return beta_hist

@jit
def hmm_backwards_jax(params, obs_seq, length=None):
    '''
    Computes the backwards probabilities

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    obs_seq: array(seq_len,)
        History of observable events

    length : array(seq_len,)
        The valid length of the observation sequence

    Returns
    -------
    * array(seq_len, n_states)
       Beta values
    '''
    seq_len = len(obs_seq)

    if length is None:
        length = seq_len

    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    beta_t = jnp.ones((n_states,))

    def scan_fn(beta_prev, t):
        beta_t = jnp.where(t > length,
                           jnp.zeros_like(beta_prev),
                           normalize((beta_prev * obs_mat[:, obs_seq[-t + 1]] * trans_mat).sum(axis=1))[0])
        return beta_t, beta_t

    ts = jnp.arange(2, seq_len + 1)
    _, beta_hist = lax.scan(scan_fn, beta_t, ts)

    beta_hist = jnp.flip(jnp.vstack([beta_t.reshape(1, n_states), beta_hist]), axis=0)

    return beta_hist


def hmm_forwards_backwards_numpy(params, obs_seq, length=None):
    '''
    Computes, for each time step, the marginal conditional probability that the Hidden Markov Model was
    in each possible state given the observations that were made at each time step, i.e.
    P(z[i] | x[0], ..., x[num_steps - 1]) for all i from 0 to num_steps - 1

    Parameters
    ----------
    params : HMMNumpy
        Hidden Markov Model

    obs_seq: array(seq_len)
        History of observed states

    Returns
    -------
    * array(seq_len, n_states)
        Alpha values

    * array(seq_len, n_states)
        Beta values

    * array(seq_len, n_states)
        Marginal conditional probability

    * float
        The loglikelihood giving log(p(x|model))
    '''
    seq_len = len(obs_seq)
    if length is None:
        length = seq_len

    ll, alpha = hmm_forwards_numpy(params, obs_seq, length)
    beta = hmm_backwards_numpy(params, obs_seq, length)

    gamma = alpha * np.roll(beta, -seq_len + length, axis=0)
    normalizer = gamma.sum(axis=1, keepdims=True)
    gamma = gamma / np.where(normalizer==0, 1, normalizer)

    return alpha, beta, gamma, ll

@jit
def hmm_forwards_backwards_jax(params, obs_seq, length=None):
    '''
    Computes, for each time step, the marginal conditional probability that the Hidden Markov Model was
    in each possible state given the observations that were made at each time step, i.e.
    P(z[i] | x[0], ..., x[num_steps - 1]) for all i from 0 to num_steps - 1

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    obs_seq: array(seq_len)
        History of observed states

    Returns
    -------
    * array(seq_len, n_states)
        Alpha values

    * array(seq_len, n_states)
        Beta values

    * array(seq_len, n_states)
        Marginal conditional probability

    * float
        The loglikelihood giving log(p(x|model))
    '''
    seq_len = len(obs_seq)
    if length is None:
        length = seq_len
    def gamma_t(t):
        gamma_t = jnp.where(t < length ,
                            alpha[t]* beta[t-length],
                            jnp.zeros((n_states,)))
        return gamma_t

    ll, alpha = hmm_forwards_jax(params, obs_seq, length)
    n_states = alpha.shape[1]

    beta = hmm_backwards_jax(params, obs_seq, length)

    ts = jnp.arange(seq_len)
    gamma = vmap(gamma_t, (0))(ts)
    #gamma = alpha * jnp.roll(beta, -seq_len + length, axis=0) #: Alternative
    gamma = vmap(lambda x: normalize(x)[0])(gamma)
    return alpha, beta, gamma, ll

def hmm_viterbi_numpy(params, obs_seq):
    """
    Compute the most probable sequence of states

    Parameters
    ----------
    params : HMMNumpy
        Hidden Markov Model

    obs_seq: array(seq_len)
        History of observed states

    Returns
    -------
    * array(seq_len)
        Sequence of most MAP probable sequence of states
    """
    seq_len = len(obs_seq)


    trans_mat, obs_mat, init_dist =  np.log(params.trans_mat),  np.log(params.obs_mat), np.log(params.init_dist)

    n_states, _ = obs_mat.shape

    first_prob = init_dist + obs_mat[:, obs_seq[0]]

    if len(obs_seq) == 1:
        return np.expand_dims(np.argmax(first_prob), axis=0)

    prev_prob = first_prob
    most_likely_sources = []

    for obs in obs_seq[1:]:
        obs_prob = obs_mat[..., obs]
        p = prev_prob[..., None] +  trans_mat + obs_prob[..., None, :]
        max_p_given_successor = np.max(p, axis=-2)
        most_likely_given_successor = np.argmax(p, axis=-2)
        prev_prob = max_p_given_successor
        most_likely_sources.append(most_likely_given_successor)

    final_prob = prev_prob
    final_state = np.argmax(final_prob)

    most_likely_initial_given_successor = np.argmax(
        trans_mat + final_prob, axis=-2)

    most_likely_sources = np.vstack([
        np.expand_dims(most_likely_initial_given_successor, axis=0),
        np.array(most_likely_sources)])

    most_likely_path, state = [], final_state

    for most_likely_source in reversed(most_likely_sources[1:]):
        state = jax.nn.one_hot(state, n_states)
        most_likely = np.sum(most_likely_source * state).astype(np.int64)
        state = most_likely
        most_likely_path.append(most_likely)

    return np.append(np.flip(most_likely_path), final_state)

@jit
def hmm_viterbi_jax(params, obs_seq, length=None):
    """
    Compute the most probable sequence of states

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    obs_seq: array(seq_len)
        History of observed states

    length : int
        Valid length of the observation sequence

    Returns
    -------
    * array(seq_len)
        Sequence of most MAP probable sequence of states
    """
    seq_len = len(obs_seq)

    if length is None:
        length = seq_len

    trans_log_probs = jax.nn.log_softmax(jnp.log(params.trans_mat))
    init_log_probs = jax.nn.log_softmax(jnp.log(params.init_dist))
    obs_mat = jnp.log(params.obs_mat)
    n_states, *_ = obs_mat.shape

    first_log_prob = init_log_probs + obs_mat[:, obs_seq[0]]

    if len(obs_seq) == 1:
        return jnp.expand_dims(jnp.argmax(first_log_prob), axis=0)

    def viterbi_forward(prev_logp, obs):
        obs_logp = obs_mat[:, obs]
        logp = prev_logp[..., None] + trans_log_probs + obs_logp[..., None, :]
        max_logp_given_successor = jnp.max(logp, axis=-2)
        most_likely_given_successor = jnp.argmax(logp, axis=-2)
        return max_logp_given_successor, most_likely_given_successor

    final_log_prob, most_likely_sources = jax.lax.scan(
        viterbi_forward, first_log_prob, obs_seq[1:])

    most_likely_initial_given_successor = jnp.argmax(
        trans_log_probs + first_log_prob, axis=-2)
    most_likely_sources = jnp.concatenate([
        jnp.expand_dims(most_likely_initial_given_successor, axis=0),
        most_likely_sources], axis=0)

    def viterbi_backward(state, most_likely_sources):
        state = jax.nn.one_hot(state, n_states)
        most_likely = jnp.sum(most_likely_sources * state).astype(jnp.int64)
        return most_likely, most_likely

    final_state = jnp.argmax(final_log_prob)
    _, most_likely_path = jax.lax.scan(
        viterbi_backward, final_state, most_likely_sources[1:], reverse=True)

    return jnp.append(most_likely_path, final_state)


###############
# Learning using EM (Baum Welch)



@dataclass
class PriorsNumpy:
   trans_pseudo_counts: np.array
   obs_pseudo_counts: np.array
   init_pseudo_counts: np.array


@dataclass
class PriorsJax:
   trans_pseudo_counts: jnp.array
   obs_pseudo_counts: jnp.array
   init_pseudo_counts: jnp.array


def init_random_params_numpy(sizes, random_state):
    """
    Initializes the components of HMM from normal distibution

    Parameters
    ----------
    sizes: List
        Consists of the number of hidden states and observable events, respectively

    random_state : int
        Seed value

    Returns
    -------
    * HMMNumpy
        Hidden Markov Model
    """
    num_hidden, num_obs = sizes
    np.random.seed(random_state)
    return HMMNumpy(softmax(np.random.randn(num_hidden, num_hidden), axis=1),
                    softmax(np.random.randn(num_hidden, num_obs), axis=1),
                    softmax(np.random.randn(num_hidden)))


def init_random_params_jax(sizes, rng_key):
    """
    Initializes the components of HMM from uniform distibution

    Parameters
    ----------
    sizes: List
        Consists of number of hidden states and observable events, respectively

    rng_key : array
        Random key of shape (2,) and dtype uint32

    Returns
    -------
    * HMMJax
        Hidden Markov Model
    """
    num_hidden, num_obs = sizes
    rng_key, rng_a, rng_b, rng_pi = jax.random.split(rng_key, 4)
    return HMMJax(jax.nn.softmax(jax.random.normal(rng_a, (num_hidden, num_hidden)), axis=1),
                  jax.nn.softmax(jax.random.normal(rng_b, (num_hidden, num_obs)), axis=1),
                  jax.nn.softmax(jax.random.normal(rng_pi, (num_hidden,))))

def compute_expected_trans_counts_numpy(params, alpha, beta, obs, T):
    """
    Computes the expected transition counts by summing ksi_{jk} for the observation given for all states j and k.
    ksi_{jk} for any time t in [0, T-1] can be calculated as the multiplication of the probability of ending
    in state j at t, the probability of starting in state k at t+1, the transition probability a_{jk} and b_{k obs[t+1]}.
    Note that ksi[t] is normalized so that the probabilities sums up to 1 for each time t in [0, T-1].

    Parameters
    ----------
    params: HMMNumpy
       Hidden Markov Model

    alpha : array
        A matrix of shape (seq_len, n_states)

    beta : array
        A matrix of shape (seq_len, n_states)

    obs : array
        One observation sequence

    T : int
        The valid length of observation sequence

    Returns
    ----------

    * array
        The matrix of shape (n_states, n_states) representing expected transition counts given obs o.
    """
    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    AA = np.zeros((n_states, n_states))  # AA[,j,k] = sum_t p(z(t)=j, z(t+1)=k|obs)

    for t in range(T - 1):
        ksi = alpha[t] * trans_mat.T * beta[t + 1] * obs_mat[:, obs[t + 1]]
        normalizer = ksi.sum()
        ksi /= 1 if normalizer==0 else ksi.sum()
        AA += ksi.T
    return AA

def compute_expected_trans_counts_jax(params, alpha, beta, observations):
    """
    Computes the expected transition counts by summing ksi_{jk} for the observation given for all states j and k.
    ksi_{jk} for any time t in [0, T-1] can be calculated as the multiplication of the probability of ending
    in state j at t, the probability of starting in state k at t+1, the transition probability a_{jk} and b_{k obs[t+1]}.
    Note that ksi[t] is normalized so that the probabilities sums up to 1 for each time t in [0, T-1].

    Parameters
    ----------
    params: HMMJax
       Hidden Markov Model

    alpha : array
        A matrix of shape (num_obs_seq, seq_len, n_states) in which each row stands for the alpha of the
        corresponding observation sequence

    beta : array
        A matrix of shape (num_obs_seq, seq_len, n_states) in which each row stands for the beta of the
        corresponding observation sequence

    observations : array
        All observation sequences

    Returns
    ----------
    * array
        A matrix of shape (n_states, n_states) representing expected transition counts
    """
    def ksi_(trans_mat, obs_mat, alpha, beta, obs):
        return (alpha * trans_mat.T * beta * obs_mat[:, obs]).T

    def count_(trans_mat, obs_mat, alpha, beta, obs):
        # AA[,j,k] = sum_t p(z(t)=j, z(t+1)=k|obs)
        AA = vmap(ksi_, in_axes=(None, None, 0, 0, 0))(trans_mat, obs_mat, alpha[:-1], beta[1:], obs[1:])
        return AA

    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist

    trans_counts = vmap(count_, in_axes=(None, None, 0, 0, 0))(trans_mat, obs_mat, alpha, beta, observations)

    trans_count_normalizer = jnp.sum(trans_counts, axis=[2, 3], keepdims=True)
    trans_count_normalizer = jnp.where(trans_count_normalizer == 0, 1, trans_count_normalizer)

    trans_counts = jnp.sum(trans_counts / trans_count_normalizer, axis=1)
    trans_counts = jnp.sum(trans_counts, axis=0)

    return trans_counts


def compute_expected_obs_counts_numpy(gamma, obs, T, n_states, n_obs):
    """
    Computes the expected observation count for each observation o by summing the probability of being at any of the
    states for each time t.
    Parameters
    ----------
    gamma : array
        A matrix of shape (seq_len, n_states)

    obs : array
        An array of shape (seq_len,)

    T : int
        The valid length of observation sequence

    n_states : int
        The number of hidden states

    n_obs : int
        The number of observable events

    Returns
    ----------
    * array
        A matrix of shape (n_states, n_obs) representing expected observation counts given observation sequence.
    """
    BB = np.zeros((n_states, n_obs))
    for t in range(T):
        o = obs[t]
        BB[:, o] += gamma[t]
    return BB

def compute_expected_obs_counts_jax(gamma, obs, n_states, n_obs):
    """
    Computes the expected observation count for each observation o by summing the probability of being at any of the
    states for each time t.
    Parameters
    ----------
    gamma : array
        A matrix of shape (seq_len, n_states)

    obs : array
        An array of shape (seq_len,)

    n_states : int
        The number of hidden states

    n_obs : int
        The number of observable events

    Returns
    ----------
    * array
        A matrix of shape (n_states, n_obs) representing expected observation counts given observation sequence.
    """
    def scan_fn(BB, elems):
        o, g = elems
        BB = index_update(BB, index[:, o], BB[:, o] + g)
        return BB, jnp.zeros((0,))

    BB = jnp.zeros((n_states, n_obs))
    BB, _ = jax.lax.scan(scan_fn, BB, (obs, gamma))
    return BB

def hmm_e_step_numpy(params, observations, valid_lengths):
    """

    Calculates the the expectation of the complete loglikelihood over the distribution of
    observations given the current parameters

    Parameters
    ----------
    params: HMMNumpy
       Hidden Markov Model

    observations : array
        All observation sequences

    valid_lengths : array
        Valid lengths of each observation sequence

    Returns
    ----------
    * array
        A matrix of shape (n_states, n_states) representing expected transition counts

    * array
        A matrix of shape (n_states, n_obs) representing expected observation counts

    * array
        An array of shape (n_states,) representing expected initial counts calculated from summing gamma[0] of each
        observation sequence

    * float
        The sum of the likelihood, p(o | lambda) where lambda stands for (trans_mat, obs_mat, init_dist) triple, for
        each observation sequence o.
    """
    N, _ = observations.shape

    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    trans_counts = np.zeros((n_states, n_states))
    obs_counts = np.zeros((n_states, n_obs))
    init_counts = np.zeros((n_states))

    loglikelihood = 0

    for obs, valid_len in zip(observations, valid_lengths):
        alpha, beta, gamma, ll = hmm_forwards_backwards_numpy(params, obs, valid_len)
        trans_counts = trans_counts + compute_expected_trans_counts_numpy(params, alpha, beta, obs, valid_len)
        obs_counts = obs_counts + compute_expected_obs_counts_numpy(gamma, obs, valid_len, n_states, n_obs)
        init_counts = init_counts + gamma[0]
        loglikelihood += ll

    return trans_counts, obs_counts, init_counts, loglikelihood

def hmm_e_step_jax(params, observations, valid_lengths):
    """

    Calculates the the expectation of the complete loglikelihood over the distribution of
    observations given the current parameters

    Parameters
    ----------
    params: HMMJax
       Hidden Markov Model

    observations : array
        All observation sequences

    valid_lengths : array
        Valid lengths of each observation sequence

    Returns
    ----------
    * array
        A matrix of shape (n_states, n_states) representing expected transition counts

    * array
        A matrix of shape (n_states, n_obs) representing expected observation counts

    * array
        An array of shape (n_states,) representing expected initial state counts calculated from summing gamma[0]
        of each observation sequence

    * float
        The sum of the likelihood, p(o | lambda) where lambda stands for (trans_mat, obs_mat, init_dist) triple, for
        each observation sequence o.
    """
    trans_mat, obs_mat, init_dist = params.trans_mat, params.obs_mat, params.init_dist
    n_states, n_obs = obs_mat.shape

    alpha, beta, gamma, ll = vmap(hmm_forwards_backwards_jax, in_axes=(None, 0, 0))(params, observations, valid_lengths)
    trans_counts = compute_expected_trans_counts_jax(params, alpha, beta, observations)

    obs_counts = vmap(compute_expected_obs_counts_jax, in_axes=(0, 0, None, None))(gamma, observations, n_states, n_obs)
    obs_counts = jnp.sum(obs_counts, axis=0)

    init_counts = jnp.sum(gamma[:, 0, :], axis=0)
    loglikelihood = jnp.sum(ll)

    return trans_counts, obs_counts, init_counts, loglikelihood

def hmm_m_step_numpy(counts, priors=None):
    """

    Recomputes new parameters from A, B and pi using max likelihood.

    Parameters
    ----------
    counts: tuple
        Consists of expected transition counts, expected observation counts, and expected initial state counts,
        respectively.

    priors : PriorsNumpy

    Returns
    ----------
    * HMMNumpy
        Hidden Markov Model

    """
    trans_counts, obs_counts, init_counts = counts

    if priors is not None:
        trans_counts = trans_counts + priors.trans_pseudo_counts
        obs_counts = obs_counts + priors.obs_pseudo_count
        init_counts = init_counts + priors.init_pseudo_counts

    A = trans_counts / trans_counts.sum(axis=1, keepdims=True)
    B = obs_counts / obs_counts.sum(axis=1, keepdims=True)
    pi = init_counts / init_counts.sum()

    return HMMNumpy(A, B, pi)

def hmm_m_step_jax(counts, priors=None):
    """

    Recomputes new parameters from A, B and pi using max likelihood.

    Parameters
    ----------
    counts: tuple
        Consists of expected transition counts, expected observation counts, and expected initial state counts,
        respectively.

    priors : PriorsNumpy

    Returns
    ----------
    * HMMJax
        Hidden Markov Model

    """
    trans_counts, obs_counts, init_counts = counts

    if priors is not None:
        trans_counts = trans_counts + priors.trans_pseudo_counts
        obs_counts = obs_counts + priors.obs_pseudo_count
        init_counts = init_counts + priors.init_pseudo_counts

    A_denom = trans_counts.sum(axis=1, keepdims=True)
    A = trans_counts / jnp.where(A_denom == 0, 1, A_denom)

    B_denom = obs_counts.sum(axis=1, keepdims=True)
    B = obs_counts / jnp.where(B_denom == 0, 1, B_denom)

    pi = init_counts / init_counts.sum()
    return HMMJax(A, B, pi)

def hmm_em_numpy(observations, valid_lengths, n_hidden=None, n_obs=None,
                 init_params=None, priors=None, num_epochs=1, random_state=None):
    """
    Implements Baum–Welch algorithm which is used for finding its components, A, B and pi.

    Parameters
    ----------
    observations: array
        All observation sequences

    valid_lengths : array
        Valid lengths of each observation sequence

    n_hidden : int
        The number of hidden states

    n_obs : int
        The number of observable events

    init_params : HMMNumpy
        Initial Hidden Markov Model

    priors : PriorsNumpy
        Priors for the components of Hidden Markov Model

    num_epochs : int
        Number of times model will be trained

    random_state: int
        Seed value

    Returns
    ----------
    * HMMNumpy
        Trained Hidden Markov Model

    * array
        Negative loglikelihoods each of which can be interpreted as the loss value at the current iteration.
    """

    if random_state is None:
        random_state = 0

    if init_params is None:
        try:
            init_params = init_random_params_numpy([n_hidden, n_obs], random_state)
        except:
            raise ValueError("n_hidden and n_obs should be specified when init_params was not given.")

    neg_loglikelihoods = []
    params = init_params

    for _ in range(num_epochs):
        trans_counts, obs_counts, init_counts, ll = hmm_e_step_numpy(params, observations, valid_lengths)
        neg_loglikelihoods.append(-ll)
        params = hmm_m_step_numpy([trans_counts, obs_counts, init_counts], priors)

    return params, neg_loglikelihoods

def hmm_em_jax(observations, valid_lengths, n_hidden=None, n_obs=None,
               init_params=None, priors=None, num_epochs=1, rng_key=None):
    """
    Implements Baum–Welch algorithm which is used for finding its components, A, B and pi.

    Parameters
    ----------
    observations: array
        All observation sequences

    valid_lengths : array
        Valid lengths of each observation sequence

    n_hidden : int
        The number of hidden states

    n_obs : int
        The number of observable events

    init_params : HMMJax
        Initial Hidden Markov Model

    priors : PriorsJax
        Priors for the components of Hidden Markov Model

    num_epochs : int
        Number of times model will be trained

    rng_key : array
        Random key of shape (2,) and dtype uint32

    Returns
    ----------
    * HMMJax
        Trained Hidden Markov Model

    * array
        Negative loglikelihoods each of which can be interpreted as the loss value at the current iteration.
    """
    if rng_key is None:
        rng_key = PRNGKey(0)

    if init_params is None:
        try:
            init_params = init_random_params_jax([n_hidden, n_obs], rng_key=rng_key)
        except:
            raise ValueError("n_hidden and n_obs should be specified when init_params was not given.")

    epochs = jnp.arange(num_epochs)

    def train_step(params, epoch):
        trans_counts, obs_counts, init_counts, ll = hmm_e_step_jax(params, observations, valid_lengths)
        params = hmm_m_step_jax([trans_counts, obs_counts, init_counts], priors)
        return params, -ll

    final_params, neg_loglikelihoods = jax.lax.scan(train_step, init_params, epochs)

    return final_params, neg_loglikelihoods


###################
# Learning using SGD




opt_init, opt_update, get_params = None, None, None

def init_random_params(sizes, rng_key):
    """
    Initializes the components of HMM from normal distibution

    Parameters
    ----------
    sizes: List
      Consists of number of hidden states and observable events, respectively

    rng_key : array
        Random key of shape (2,) and dtype uint32

    Returns
    -------
    * array(num_hidden, num_hidden)
      Transition probability matrix

    * array(num_hidden, num_obs)
      Emission probability matrix

    * array(1, num_hidden)
      Initial distribution probabilities
    """
    num_hidden, num_obs = sizes
    rng_key, rng_a, rng_b, rng_pi = split(rng_key, 4)
    return HMMJax(normal(rng_a, (num_hidden, num_hidden)),
                  normal(rng_b, (num_hidden, num_obs)),
                  normal(rng_pi, (num_hidden,)))


@jit
def loss_fn(params, batch, lens):
    """
    Objective function of hidden markov models for discrete observations. It returns the mean of the negative
    loglikelihood of the sequence of observations

    Parameters
    ----------
    params : HMMJax
        Hidden Markov Model

    batch: array(N, max_len)
        Minibatch consisting of observation sequences

    lens : array(N, seq_len)
        Consists of the valid length of each observation sequence in the minibatch

    Returns
    -------
    * float
        The mean negative loglikelihood of the minibatch
    """
    params_soft = HMMJax(softmax(params.trans_mat, axis=1),
                         softmax(params.obs_mat, axis=1),
                         softmax(params.init_dist))
    return -hmm_loglikelihood_jax(params_soft, batch, lens).mean()


@jit
def update(i, opt_state, batch, lens):
    """
    Objective function of hidden markov models for discrete observations. It returns the mean of the negative
    loglikelihood of the sequence of observations

    Parameters
    ----------
    i : int
        Specifies the current iteration

    opt_state : OptimizerState

    batch: array(N, max_len)
        Minibatch consisting of observation sequences

    lens : array(N, seq_len)
        Consists of the valid length of each observation sequence in the minibatch

    Returns
    -------
    * OptimizerState

    * float
        The mean negative loglikelihood of the minibatch, i.e. loss value for the current iteration.
    """
    params = get_params(opt_state)
    loss, grads = jax.value_and_grad(loss_fn)(params, batch, lens)
    return opt_update(i, grads, opt_state), loss


def fit(observations, lens, num_hidden, num_obs, batch_size, optimizer,rng_key=None, num_epochs=1):
    """
    Trains the HMM model with the given number of hidden states and observations via any optimizer.

    Parameters
    ----------
    observations: array(N, seq_len)
        All observation sequences

    lens : array(N, seq_len)
        Consists of the valid length of each observation sequence

    num_hidden : int
        The number of hidden state

    num_obs : int
        The number of observable events

    batch_size : int
        The number of observation sequences that will be included in each minibatch

    optimizer : jax.experimental.optimizers.Optimizer
        Optimizer that is used during training

    num_epochs : int
        The total number of iterations

    Returns
    -------
    * HMMJax
        Hidden Markov Model

    * array
      Consists of training losses
    """
    global opt_init, opt_update, get_params

    if rng_key is None:
        rng_key = PRNGKey(0)

    rng_init, rng_iter = split(rng_key)
    params = init_random_params([num_hidden, num_obs], rng_init)
    opt_init, opt_update, get_params = optimizer
    opt_state = opt_init(params)
    itercount = itertools.count()

    def epoch_step(opt_state, key):

        def train_step(opt_state, params):
            batch, length = params
            opt_state, loss = update(next(itercount), opt_state, batch, length)
            return opt_state, loss

        batches, valid_lens = hmm_sample_minibatches(observations, lens, batch_size, key)
        params = (batches, valid_lens)
        opt_state, losses = jax.lax.scan(train_step, opt_state, params)
        return opt_state, losses.mean()

    epochs = split(rng_iter, num_epochs)
    opt_state, losses = jax.lax.scan(epoch_step, opt_state, epochs)

    losses = losses.flatten()

    params = get_params(opt_state)
    params = HMMJax(softmax(params.trans_mat, axis=1),
                    softmax(params.obs_mat, axis=1),
                    softmax(params.init_dist))
    return params, losses