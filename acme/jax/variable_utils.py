# python3
# Copyright 2018 DeepMind Technologies Limited. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Variable utilities for JAX."""

from concurrent import futures
from typing import List, Optional

from acme import core

import haiku as hk
import jax


class VariableClient:
  """A variable client for updating variables from a remote source."""

  def __init__(self,
               client: core.VariableSource,
               key: str,
               update_period: int = 1,
               device: str = None):
    """Initializes the object.

    Args:
      client: a variable source
      key: what variables to request
      update_period: update period
      device: if not None, defines to which device variables should be put to
    """
    self._key = key
    self._update_period = update_period
    self._call_counter = 0
    self._client = client
    self._params = None
    self._device = None
    if device:
      self._device = jax.devices(device)[0]

    self._executor = futures.ThreadPoolExecutor(max_workers=1)
    self._request = lambda: client.get_variables([self._key])
    self._future: Optional[futures.Future] = None
    self._async_request = lambda: self._executor.submit(self._request)

  def update(self, wait: bool = False):
    """Periodically updates the variables with the latest copy from the source.

    If wait is True, a blocking request is executed. Any active request will be
    cancelled.
    If wait is False, this method makes an asynchronous request for variables.

    Args:
      wait: if True, executes blocking update.
    """
    # Track calls (we only update periodically).
    if self._call_counter < self._update_period:
      self._call_counter += 1

    # Return if it's not time to fetch another update.
    if self._call_counter < self._update_period:
      return

    if wait:
      # Cancel any already running request.
      self._future = None
      self._call_counter = 0
      self.update_and_wait()
      return

    # Return early if we are still waiting for a previous request to come back.
    if self._future and self._future.running():
      return

    # Get a future and add the copy function as a callback.
    self._call_counter = 0
    self._future = self._async_request()
    self._future.add_done_callback(lambda f: self._callback(f.result()))

  def update_and_wait(self):
    """Immediately update and block until we get the result."""
    self._callback(self._request())

  def _callback(self, params_list: List[hk.Params]):
    assert len(params_list) == 1
    if self._device:
      # Move variables to a proper device.
      self._params = jax.device_put(params_list[0], self._device)
    else:
      self._params = params_list[0]

  @property
  def params(self) -> hk.Params:
    if self._params is None:
      self.update_and_wait()
    return self._params
