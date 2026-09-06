"""Import a local ADK agent from a ``module:attribute`` spec.

Shared by ``local_agent_evaluation.py`` and ``generate_eval_dataset.py``. Both
have to resolve the same spec to the same object -- the generator reads the
agent's instruction to synthesise scenarios, the runner drives it -- and a
divergence between the two would surface as scenarios generated against one
agent and scored against another. Factored out so the two cannot drift, for the
same reason ``usage_logger`` imports its column map from ``usage_store``.
"""

import importlib
import os
import sys


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def configure_vertex_env(project, model_location):
    """Point the *agent's own* model calls at Vertex, before the agent loads.

    Two separate clients are in play and only one of them is ours. We construct
    ``agentplatform.Client`` explicitly, so it takes whatever location we pass.
    The agent's model client is built by ADK, deep inside `run_inference`, and
    configures itself entirely from the environment -- so the environment is the
    only channel we have to it.

    Left alone it goes wrong twice:

    - ``google.genai`` reads ``GOOGLE_GENAI_USE_VERTEXAI`` and treats unset as
      false (_api_client.py, ``env_vertexai``), so the agent's calls go to the
      Gemini Developer API, which wants an API key nobody has. That surfaces as
      ``ValueError: No API Key was provided`` from inside the eval, where it
      reads like a problem with the eval rather than a missing export.
    - ``GOOGLE_CLOUD_LOCATION`` is read by that same client *and* by our
      ``--location`` default, which are not the same thing. The evals API is
      regional; Gemini models are reached at ``global``. Exporting one value to
      satisfy the agent silently redirects the eval, and vice versa.

    So the two are split: ``--location`` is the evals region and is passed to
    the client by hand, ``--model-location`` is the agent's and is what goes
    into the environment here. Call this after parsing arguments (so the
    ``--location`` default still sees the caller's own environment) and before
    ``load_agent``, since importing the agent's module may build the client.

    An explicitly set ``GOOGLE_GENAI_USE_VERTEXAI`` is left alone -- someone who
    set it to false meant it, and silently overriding it would break the one
    case this cannot distinguish from a mistake.
    """
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    if project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_LOCATION"] = model_location


def load_agent(spec):
    """Import an ADK agent from a 'module:attribute' spec."""
    from google.adk.agents import BaseAgent

    if ":" not in spec:
        fail(f"--agent must be 'module:attribute', got {spec!r}")
    module_name, _, attribute = spec.partition(":")

    sys.path.insert(0, os.getcwd())
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        fail(
            f"cannot import {module_name!r}: {exc}\n"
            "Run this from the repository root, where the agent's package lives."
        )

    try:
        agent = getattr(module, attribute)
    except AttributeError:
        exported = [n for n in dir(module) if not n.startswith("_")]
        fail(f"{module_name!r} has no {attribute!r}. It exports: {', '.join(exported)}")

    if not isinstance(agent, BaseAgent) and callable(agent):
        try:
            agent = agent()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            fail(
                f"{spec} is callable but calling it failed: {exc}\n"
                "Point --agent at the ADK agent object, or at a factory that takes "
                "no arguments."
            )
    if not isinstance(agent, BaseAgent):
        fail(
            f"{spec} is a {type(agent).__name__}, not an ADK agent. Point --agent at "
            "the Agent/LlmAgent object itself, not at a wrapper class around it."
        )
    return agent
