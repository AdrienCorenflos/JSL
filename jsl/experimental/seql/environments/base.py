import jax.numpy as jnp
from jax import random, jit, nn, vmap

import haiku as hk

import chex
from typing import Callable, List, Tuple

import numpy as np
from sklearn.preprocessing import PolynomialFeatures

from jsl.experimental.seql.environments.sequential_data_env import SequentialDataEnvironment
from jsl.experimental.seql.environments.sequential_torch_env import SequentialTorchEnvironment


def gaussian_sampler(key: chex.PRNGKey, shape: Tuple) -> chex.Array:
    # shape: (num_samples: int, input_dim: int)
    return random.normal(key, shape)

def make_evenly_spaced_x_sampler(max_val: float, use_bias: bool= True, min_val: float = 0)->Callable:

    def eveny_spaced_x_sampler(key: chex.PRNGKey, shape: Tuple)->chex.Array:
        if len(shape)==1:
            shape = (shape[0], 1)
        nsamples, nfeatures = shape
        assert nfeatures == 1 or nfeatures == 2

        if nfeatures==1:
            X = jnp.linspace(min_val, max_val, nsamples)
            if use_bias:
                X = jnp.c_[jnp.ones(nsamples), X]
            else:
                X = X.reshape((-1, 1))
        else:
            x = jnp.linspace(min_val, max_val, nsamples)
            y = jnp.linspace(min_val, max_val, nsamples)
            xx, yy= jnp.meshgrid(x,y)
            X = jnp.array((xx.ravel(), yy.ravel())).T
        return X
        
    return eveny_spaced_x_sampler


def make_bimodel_sampler(mixing_parameter: float,
                         means: List[float],
                         variances: List[float]):
    mu1, mu2 = means
    sigma1, sigma2 = variances

    def check_unimodal():
        d = jnp.abs(mu1 - mu2) / 2 * jnp.sqrt(mu1 * mu2)
        lhs = jnp.abs(jnp.log(1-mixing_parameter) - jnp.log(mixing_parameter))     
        rhs = 2 * jnp.log(d - jnp.sqrt(d**2 - 1)) + 2 * d * jnp.sqrt(d**2 - 1)
        return lhs >= rhs
    
    is_unimodal = check_unimodal()
    if is_unimodal:
        raise TypeError("The mixture is unimodal.")

    def bimodel_sampler(key: chex.PRNGKey, shape: Tuple)-> chex.Array:
        nsamples, nfeatures = shape
        n1 = int(nsamples * mixing_parameter)
        n2 = int(nsamples * (1 - mixing_parameter))
        
        x1_key, x2_key = random.split(key)
        x1 = gaussian_sampler(x1_key, (n1, nfeatures))*sigma1 + mu1
        x2 = gaussian_sampler(x2_key, (n2, nfeatures))*sigma2 + mu2
        return jnp.vstack([x1, x2])
        
    return bimodel_sampler

def make_random_poly_classification_environment(key: chex.PRNGKey,
                                                degree: int,
                                                ntrain: int,
                                                ntest: int,
                                                nclasses:int = 2,
                                                nfeatures: int = 1,
                                                obs_noise: float=0.01,
                                                train_batch_size: int=1,
                                                test_batch_size: int=1,
                                                x_train_generator: Callable=gaussian_sampler,
                                                x_test_generator: Callable=gaussian_sampler):


  train_key, test_key = random.split(key)
  X_train = x_train_generator(train_key, (ntrain, nfeatures))
  X_test = x_test_generator(test_key, (ntest, nfeatures))
  X = jnp.vstack([X_train, X_test])

  poly = PolynomialFeatures(degree)
  Phi = jnp.array(poly.fit_transform(X), dtype=jnp.float32)

  D = Phi.shape[-1]
  w = random.normal(key, (D, nclasses))

  if obs_noise > 0.0:
    nsamples = ntrain + ntest
    noise = random.normal(key, (nsamples, 1)) * obs_noise

  Y = jnp.argmax(Phi @ w + noise, axis=-1).reshape((-1, 1))
  
  X_train = Phi[:ntrain]
  X_test = Phi[ntrain:]
  y_train = Y[:ntrain]
  y_test = Y[ntrain:]
  
  env = SequentialDataEnvironment(X_train, y_train,
                                X_test, y_test,
                                train_batch_size, test_batch_size,
                                classification=True)
  
  return env

def make_random_poly_regression_environment(key: chex.PRNGKey,
                                            degree: int,
                                            ntrain: int,
                                            ntest: int,
                                            obs_noise: float=0.01,
                                            train_batch_size: int=1,
                                            test_batch_size: int=1,
                                            x_train_generator: Callable=gaussian_sampler,
                                            x_test_generator: Callable=gaussian_sampler):


  train_key, test_key = random.split(key)
  X_train = x_train_generator(train_key, (ntrain, 1))
  X_test = x_test_generator(test_key, (ntest, 1))
  X = jnp.vstack([X_train, X_test])

  poly = PolynomialFeatures(degree)
  Phi = jnp.array(poly.fit_transform(X), dtype=jnp.float32)

  D = Phi.shape[-1]
  w = random.normal(key, (D, 1))

  if obs_noise > 0.0:
    nsamples = ntrain + ntest
    noise = random.normal(key, (nsamples, 1)) * obs_noise
  Y = Phi @ w + noise
  
  X_train = Phi[:ntrain]
  X_test = Phi[ntrain:]
  y_train = Y[:ntrain]
  y_test = Y[ntrain:]
  
  env = SequentialDataEnvironment(X_train, y_train,
                                X_test, y_test,
                                train_batch_size, test_batch_size,
                                classification=False)
  
  return env

def make_random_linear_classification_environment(key: chex.PRNGKey,
                                            nfeatures: int,
                                            ntrain: int,
                                            ntest: int,
                                            ntargets: int = 2,
                                            bias: float=0.0,
                                            obs_noise: float=0.0,
                                            train_batch_size: int=1,
                                            test_batch_size: int=1,
                                            x_train_generator: Callable=gaussian_sampler,
                                            x_test_generator: Callable=gaussian_sampler):
    # https://github.com/scikit-learn/scikit-learn/blob/7e1e6d09bcc2eaeba98f7e737aac2ac782f0e5f1/sklearn/datasets/_samples_generator.py#L506

    # Randomly generate a well conditioned input set
    train_key, test_key, w_key, noise_key = random.split(key, 4) 

    X_train = x_train_generator(train_key, (ntrain, nfeatures))
    X_test = x_test_generator(test_key, (ntest, nfeatures))
    X = jnp.vstack([X_train, X_test])

    # Generate a ground truth model with only n_informative features being non
    # zeros (the other features are not correlated to y and should be ignored
    # by a sparsifying regularizers such as L1 or elastic net)
    ground_truth = 100 * random.normal(w_key, (nfeatures, ntargets))

    Y = jnp.argmax(jnp.dot(X, ground_truth) + bias, axis=-1).reshape((-1, 1))
    
    if bias:
        X = jnp.hstack([jnp.ones((len(X), 1)), X])

    # Add noise
    if obs_noise > 0.0:
        Y += obs_noise * random.normal(noise_key, size=Y.shape)

    X_train = X[:ntrain]
    X_test = X[ntrain:]
    y_train = Y[:ntrain]
    y_test = Y[ntrain:]

    env = SequentialDataEnvironment(X_train, y_train,
                                    X_test, y_test,
                                    train_batch_size, test_batch_size,
                                    classification=False)
    return env

def make_random_linear_regression_environment(key: chex.PRNGKey,
                                            nfeatures: int,
                                            ntargets: int,
                                            ntrain: int,
                                            ntest: int,
                                            bias: float=0.0,
                                            obs_noise: float=0.0,
                                            train_batch_size: int=1,
                                            test_batch_size: int=1,
                                            x_train_generator: Callable=gaussian_sampler,
                                            x_test_generator: Callable=gaussian_sampler):
    # https://github.com/scikit-learn/scikit-learn/blob/7e1e6d09bcc2eaeba98f7e737aac2ac782f0e5f1/sklearn/datasets/_samples_generator.py#L506

    nsamples = ntrain + ntest
    # Randomly generate a well conditioned input set
    train_key, test_key, w_key, noise_key = random.split(key, 4) 

    X_train = x_train_generator(train_key, (ntrain, nfeatures))
    X_test = x_test_generator(test_key, (ntest, nfeatures))
    X = jnp.vstack([X_train, X_test])

    # Generate a ground truth model with only n_informative features being non
    # zeros (the other features are not correlated to y and should be ignored
    # by a sparsifying regularizers such as L1 or elastic net)
    ground_truth = 100 * random.normal(w_key,(nfeatures, ntargets))

    Y = jnp.dot(X, ground_truth) + bias
    if bias:
        X = jnp.hstack([jnp.ones((len(X), 1)), X])

    # Add noise
    if obs_noise > 0.0:
        Y += obs_noise * random.normal(noise_key, size=Y.shape)

    X_train = X[:ntrain]
    X_test = X[ntrain:]
    y_train = Y[:ntrain]
    y_test = Y[ntrain:]

    env = SequentialDataEnvironment(X_train, y_train,
                                    X_test, y_test,
                                    train_batch_size, test_batch_size,
                                    classification=False)
    return env

def make_mlp(key: chex.PRNGKey,
            nfeatures: int,
            ntargets: int,
            temperature: float,
            hidden_layer_sizes: List[int]):

    assert hidden_layer_sizes != []

    # Generating the logit function
    def net_fn(x: chex.Array):
        """Defining the generative model MLP."""            
        hidden = hidden_layer_sizes[0]
        y = hk.Linear(
            output_size=hidden,
            b_init=hk.initializers.RandomNormal(1./jnp.sqrt(nfeatures)),
        )(x)
        y = nn.relu(y)

        for hidden in hidden_layer_sizes[1:]:
            y = hk.Linear(hidden)(y)
            y = nn.relu(y)
        return hk.Linear(ntargets)(y)
  
    transformed = hk.without_apply_rng(hk.transform(net_fn))

    dummy_input = jnp.zeros([1, nfeatures])
    params = transformed.init(key, dummy_input)

    assert temperature > 0.0
    
    def forward(x: chex.Array):
        return transformed.apply(params, x) / temperature

    y_predictor = jit(forward)

    return y_predictor

def make_classification_mlp_environment(key: chex.PRNGKey,
                                        nfeatures: int,
                                        ntargets: int,
                                        ntrain: int,
                                        ntest: int,
                                        temperature: float,
                                        hidden_layer_sizes: List[int],
                                        train_batch_size: int=1,
                                        test_batch_size: int=1,
                                        x_train_generator: Callable=gaussian_sampler,
                                        x_test_generator: Callable=gaussian_sampler):

    train_key, test_key, y_key = random.split(key, 3)
    y_predictor = make_mlp(y_key,
                    nfeatures,
                    ntargets,
                    temperature,
                    hidden_layer_sizes)

    # Generates training data for given problem
    X_train = x_train_generator(train_key, (ntrain, nfeatures))
    X_test = x_test_generator(test_key, (ntest, nfeatures))
    X = jnp.vstack([X_train, X_test])

    # Generate environment function across x_train
    train_logits = y_predictor(X)  # [n_train, n_class]
    train_probs = nn.softmax(train_logits, axis=-1)

    # Generate training data.
    def sample_output(probs: chex.Array, key: chex.PRNGKey) -> chex.Array:
        return random.choice(key, ntargets, shape=(1,), p=probs)
    
    nsamples = ntrain + ntest
    y_keys = random.split(y_key, nsamples)

    Y = vmap(sample_output)(train_probs, y_keys)

    X_train = X[:ntrain]
    X_test = X[ntrain:]
    y_train = Y[:ntrain]
    y_test = Y[ntrain:]

    env = SequentialDataEnvironment(X_train, y_train,
                                    X_test, y_test,
                                    train_batch_size, test_batch_size,
                                    classification=True)
    return env


def make_regression_mlp_environment(key: chex.PRNGKey,
                                    nfeatures: int,
                                    ntargets: int,
                                    ntrain: int,
                                    ntest: int,
                                    temperature: float,
                                    hidden_layer_sizes: List[int],
                                    train_batch_size: int=1,
                                    test_batch_size: int=1,
                                    x_train_generator: Callable=gaussian_sampler,
                                    x_test_generator: Callable=gaussian_sampler):

    train_key, test_key, y_key = random.split(key, 3)
    y_predictor = make_mlp(y_key,
                    nfeatures,
                    ntargets,
                    temperature,
                    hidden_layer_sizes)

    # Generates training data for given problem
    X_train = x_train_generator(train_key, (ntrain, nfeatures))
    X_test = x_test_generator(test_key, (ntest, nfeatures))
    X = jnp.vstack([X_train, X_test])

    # Generate environment function across x_train
    Y = y_predictor(X)  # [n_train, output_dim]
    
    X_train = X[:ntrain]
    X_test = X[ntrain:]
    y_train = Y[:ntrain]
    y_test = Y[ntrain:]

    env = SequentialDataEnvironment(X_train, y_train,
                                    X_test, y_test,
                                    train_batch_size, test_batch_size,
                                    classification=False)
    return env
    

def make_environment_from_torch_dataset(dataset: Callable,
                                        classification: bool,
                                        train_batch_size: int=1,
                                        test_batch_size: int=1):
    env = SequentialTorchEnvironment(dataset,
                                    train_batch_size,
                                    test_batch_size,
                                    classification)
    return env