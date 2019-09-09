import sys
import json
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import tensorflow as tf
import numpy as np
import tensorflow_probability as tfp

from custom_lbfgs import lbfgs, Struct

class AdvNeuralNetwork(object):
  def __init__(self, hp, logger, ub, lb):
    
    # Setting up the optimizers with the previously defined hyper-parameters
    # self.nt_config = Struct()
    # self.nt_config.learningRate = hp["nt_lr"]
    # self.nt_config.maxIter = hp["nt_epochs"]
    # self.nt_config.nCorrection = hp["nt_ncorr"]
    # self.nt_config.tolFun = 1.0 * np.finfo(float).eps
    self.epochs = hp["tf_epochs"]
    self.optimizer_KL = tf.keras.optimizers.Adam(
      learning_rate=hp["tf_lr"],
      beta_1=hp["tf_b1"],
      epsilon=hp["tf_eps"])
    self.optimizer_T = tf.keras.optimizers.Adam(
      learning_rate=hp["tf_lr"],
      beta_1=hp["tf_b1"],
      epsilon=hp["tf_eps"])

    # Descriptive Keras models
    self.model_p = self.declare_model(hp["layers_P"])
    self.model_q = self.declare_model(hp["layers_Q"])
    self.model_t = self.declare_model(hp["layers_T"])

    # Hp
    self.X_dim = hp["X_dim"]
    self.T_dim = hp["T_dim"]
    self.Y_dim = hp["Y_dim"]
    self.Z_dim = hp["Z_dim"]
    self.lamda = hp["lamda"]
    self.beta = hp["beta"]
    self.k1 = hp["k1"]
    self.k2 = hp["k2"]

    # self.setup_weights_tracking()

    self.logger = logger
    self.dtype = tf.float32

  def declare_model(self, layers):
    model = tf.keras.Sequential()
    model.add(tf.keras.layers.InputLayer(input_shape=(layers[0],)))
    for width in layers[1:]:
       model.add(tf.keras.layers.Dense(
          width, activation=tf.nn.tanh,
          kernel_initializer="glorot_normal"))
    return model

  def setup_weights_tracking(self, layers):
    # Computing the sizes of weights/biases for future decomposition
    self.sizes_w = []
    self.sizes_b = []
    for i, width in enumerate(layers):
      if i != 1:
        self.sizes_w.append(int(width * layers[1]))
        self.sizes_b.append(int(width if i != 0 else layers[1]))
    
  # Defining custom loss
  def loss(self, u, u_pred):
    return tf.reduce_mean(tf.square(u - u_pred))

  def grad(self, X, u):
    with tf.GradientTape() as tape:
      loss_value = self.loss(u, self.model_p(X))
    return loss_value, tape.gradient(loss_value, self.wrap_training_variables())

  def wrap_training_variables(self):
    var = self.model_p.trainable_variables
    return var

  def get_params(self, numpy=False):
    return []

  def get_weights(self, convert_to_tensor=True):
    w = []
    for layer in self.model_p.layers[1:]:
      weights_biases = layer.get_weights()
      weights = weights_biases[0].flatten()
      biases = weights_biases[1]
      w.extend(weights)
      w.extend(biases)
    if convert_to_tensor:
      w = tf.convert_to_tensor(w, dtype=self.dtype)
    return w

  def set_weights(self, w):
    for i, layer in enumerate(self.model.layers[1:]):
      start_weights = sum(self.sizes_w[:i]) + sum(self.sizes_b[:i])
      end_weights = sum(self.sizes_w[:i+1]) + sum(self.sizes_b[:i])
      weights = w[start_weights:end_weights]
      w_div = int(self.sizes_w[i] / self.sizes_b[i])
      weights = tf.reshape(weights, [w_div, self.sizes_b[i]])
      biases = w[end_weights:end_weights + self.sizes_b[i]]
      weights_biases = [weights, biases]
      layer.set_weights(weights_biases)

  def get_loss_and_flat_grad(self, X, u):
    def loss_and_flat_grad(w):
      with tf.GradientTape() as tape:
        self.set_weights(w)
        loss_value = self.loss(u, self.model_p(X))
      grad = tape.gradient(loss_value, self.wrap_training_variables())
      grad_flat = []
      for g in grad:
        grad_flat.append(tf.reshape(g, [-1]))
      grad_flat =  tf.concat(grad_flat, 0)
      return loss_value, grad_flat
      
    return loss_and_flat_grad

  def summary(self):
    return self.model_p.summary()

  # The training function
  def fit(self, X_u, u):
    self.logger.log_train_start(self)

    # Creating the tensors
    X_u = tf.convert_to_tensor(X_u, dtype=self.dtype)
    u = tf.convert_to_tensor(u, dtype=self.dtype)

    self.logger.log_train_opt("Adam")
    for epoch in range(self.epochs):
      # Optimization step
      loss_value, grads = self.grad(X_u, u)
      self.optimizer_KL.apply_gradients(zip(grads, self.wrap_training_variables()))
      self.logger.log_train_epoch(epoch, loss_value)
    
    # self.logger.log_train_opt("LBFGS")
    # loss_and_flat_grad = self.get_loss_and_flat_grad(X_u, u)
    # tfp.optimizer.lbfgs_minimize(
    #   loss_and_flat_grad,
    #   initial_position=self.get_weights(),
    #   num_correction_pairs=nt_config.nCorrection,
    #   max_iterations=nt_config.maxIter,
    #   f_relative_tolerance=nt_config.tolFun,
    #   tolerance=nt_config.tolFun,
    #   parallel_iterations=6)
    # lbfgs(loss_and_flat_grad,
    #   self.get_weights(),
    #   self.nt_config, Struct(), True,
    #   lambda epoch, loss, is_iter:
    #     self.logger.log_train_epoch(epoch, loss, "", is_iter))

    self.logger.log_train_end(self.epochs + self.nt_config.maxIter)

  def predict(self, X_star):
    u_pred = self.model_p(X_star)
    return u_pred.numpy()