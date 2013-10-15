#!/usr/bin/env python
"""Debugging flows for the console."""

import getpass
import os
import pdb
import pickle
import tempfile
import time

from grr.client import actions

from grr.lib import access_control
from grr.lib import aff4
from grr.lib import flow
from grr.lib import queue_manager
from grr.lib import rdfvalue
from grr.lib import worker
from grr.proto import flows_pb2


class ClientActionArgs(rdfvalue.RDFProtoStruct):
  protobuf = flows_pb2.ClientActionArgs

  def GetActionArgsClass(self):
    if self.action:
      action_cls = actions.ActionPlugin.classes.get(self.action)
      if action_cls is None:
        raise ValueError("Client Action '%s' not known." % self.action)

      # The required semantic type for this field is in the client action's
      # in_rdfvalue.
      return action_cls.in_rdfvalue


class ClientAction(flow.GRRFlow):
  """A Simple flow to execute any client action."""
  args_type = ClientActionArgs

  @flow.StateHandler(next_state="Print")
  def Start(self):
    if self.args.save_to:
      if not os.path.isdir(self.args.save_to):
        os.makedirs(self.args.save_to, 0700)
    self.CallClient(self.args.action, request=self.args.action_args,
                    next_state="Print")

  @flow.StateHandler()
  def Print(self, responses):
    """Dump the responses to a pickle file or allow for breaking."""
    if not responses.success:
      self.Log("ClientAction %s failed. Staus: %s" % (self.args.action,
                                                      responses.status))

    if self.args.break_pdb:
      pdb.set_trace()
    if self.args.save_to:
      self._SaveResponses(responses)

  def _SaveResponses(self, responses):
    """Save responses to pickle files."""
    if responses:
      fd = None
      try:
        fdint, fname = tempfile.mkstemp(prefix="responses-",
                                        dir=self.args.save_to)
        fd = os.fdopen(fdint, "wb")
        pickle.dump(responses, fd)
        self.Log("Wrote %d responses to %s", len(responses), fname)
      finally:
        if fd: fd.close()


class ConsoleDebugFlowArgs(rdfvalue.RDFProtoStruct):
  protobuf = flows_pb2.ConsoleDebugFlowArgs

  def GetFlowArgsClass(self):
    if self.flow:
      flow_cls = flow.GRRFlow.classes.get(self.flow)
      if flow_cls is None:
        raise ValueError("Flow '%s' not known." % self.flow)

      # The required semantic type for this field is in args_type.
      return flow_cls.args_type


class ConsoleDebugFlow(flow.GRRFlow):
  """A Simple console flow to execute any flow and recieve back responses."""
  args_type = ConsoleDebugFlowArgs

  @flow.StateHandler(next_state="Print")
  def Start(self):
    if self.args.save_to:
      if not os.path.isdir(self.args.save_to):
        os.makedirs(self.args.save_to, 0700)
    self.CallFlow(self.args.flow, next_state="Print",
                  **self.args.args.ToDict())

  @flow.StateHandler()
  def Print(self, responses):
    """Dump the responses to a pickle file or allow for breaking."""
    if not responses.success:
      self.Log("ConsoleDebugFlow %s failed. Staus: %s" % (self.args.flow,
                                                          responses.status))

    self.Log("Got %d responses", len(responses))
    for response in responses:
      print response
    if self.args.break_pdb:
      pdb.set_trace()
    if self.args.save_to:
      self._SaveResponses(responses)

  def _SaveResponses(self, responses):
    """Save responses to pickle files."""
    if responses:
      fd = None
      try:
        fdint, fname = tempfile.mkstemp(prefix="responses-",
                                        dir=self.args.save_to)
        fd = os.fdopen(fdint, "wb")
        pickle.dump(responses, fd)
        self.Log("Wrote %d responses to %s", len(responses), fname)
      finally:
        if fd: fd.close()


def StartFlowAndWait(client_id, flow_name, **kwargs):
  """Launches the flow and waits for it to complete.

  Args:
     client_id: The client common name we issue the request.
     flow_name: The name of the flow to launch.
     **kwargs: passthrough to flow.

  Returns:
     A GRRFlow object.
  """
  session_id = flow.GRRFlow.StartFlow(client_id=client_id,
                                      flow_name=flow_name, **kwargs)
  while 1:
    time.sleep(1)
    with aff4.FACTORY.Open(session_id) as flow_obj:
      with flow_obj.GetRunner() as runner:
        if not runner.IsRunning():
          break

  return flow_obj


def StartFlowAndWorker(client_id, flow_name, **kwargs):
  """Launches the flow and worker and waits for it to finish.

  Args:
     client_id: The client common name we issue the request.
     flow_name: The name of the flow to launch.
     **kwargs: passthrough to flow.

  Returns:
     A GRRFlow object.

  Note: you need raw access to run this flow as it requires running a worker.
  """
  queue = rdfvalue.RDFURN("DEBUG-%s-" % getpass.getuser())
  session_id = flow.GRRFlow.StartFlow(client_id=client_id,
                                      flow_name=flow_name, queue=queue,
                                      **kwargs)
  # Empty token, only works with raw access.
  worker_thrd = worker.GRRWorker(
      queue=queue, token=access_control.ACLToken(username="test"),
      threadpool_size=1)
  while True:
    try:
      worker_thrd.RunOnce()
    except KeyboardInterrupt:
      print "exiting"
      worker_thrd.thread_pool.Join()
      break

    time.sleep(2)
    with aff4.FACTORY.Open(session_id) as flow_obj:
      with flow_obj.GetRunner() as runner:
        if not runner.IsRunning():
          break

  # Terminate the worker threads
  worker_thrd.thread_pool.Join()

  return flow_obj


def TestClientActionWithWorker(client_id, client_action, print_request=False,
                               break_pdb=True, **kwargs):
  """Run a client action on a client and break on return."""
  action_cls = actions.ActionPlugin.classes[client_action]
  request = action_cls.in_rdfvalue(**kwargs)
  if print_request:
    print str(request)
  StartFlowAndWorker(client_id, flow_name="ClientAction", action=client_action,
                     break_pdb=break_pdb, action_args=request)


def WakeStuckFlow(session_id):
  """Wake up stuck flows.

  A stuck flow is one which is waiting for the client to do something, but the
  client requests have been removed from the client queue. This can happen if
  the system is too loaded and the client messages have TTLed out. In this case
  we reschedule the client requests for this session.

  Args:
    session_id: The session for the flow to wake.

  Returns:
    The total number of client messages re-queued.
  """
  session_id = rdfvalue.SessionID(session_id)
  woken = 0
  checked_pending = False

  with queue_manager.QueueManager() as manager:
    for request, responses in manager.FetchRequestsAndResponses(session_id):
      # We need to check if there are client requests pending.
      if not checked_pending:
        task = manager.Query(request.client_id,
                             task_id="task:%s" % request.request.task_id)

        if task:
          # Client has tasks pending already.
          return

        checked_pending = True

      if not responses or responses[-1].type != rdfvalue.GrrMessage.Type.STATUS:
        manager.QueueClientMessage(request.request)
        woken += 1

      if responses and responses[-1].type == rdfvalue.GrrMessage.Type.STATUS:
        manager.QueueNotification(session_id)

  return woken
