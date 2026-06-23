import os
from typing import Any
import re
import sys
import json
import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.workflow import Workflow
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from app.config import config

# Initialize models
model_instance = Gemini(model=config.model)

# -----------------------------------------------------------------------------
# MCP SERVER & TOOLS SETUP
# -----------------------------------------------------------------------------

# Stdio connection params to run the local MCP server process
mcp_server_params = StdioServerParameters(
    command=sys.executable,
    args=["-m", "app.mcp_server"]
)

# Connect tools filtered for each sub-agent
medication_tools = McpToolset(
    connection_params=StdioConnectionParams(server_params=mcp_server_params),
    tool_filter=["get_medications", "schedule_medication"]
)

wellness_tools = McpToolset(
    connection_params=StdioConnectionParams(server_params=mcp_server_params),
    tool_filter=["record_wellness_check", "get_brain_teaser"]
)

# -----------------------------------------------------------------------------
# SECURITY CHECKPOINT & AUDIT LOGGING
# -----------------------------------------------------------------------------

# Setup security audit log file
audit_log_path = "security_audit.log"

def log_audit_event(severity: str, event_type: str, details: dict):
    log_data = {
        "timestamp": datetime.datetime.now(ZoneInfo("UTC")).isoformat() + "Z",
        "severity": severity,
        "event_type": event_type,
        "details": details
    }
    with open(audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_data) + "\n")

def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    """Workflow node checking for prompt injections and scrubbing sensitive PII."""
    user_input = ""
    if hasattr(node_input, "parts") and node_input.parts:
        user_input = "".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        user_input = node_input
    
    scrubbed_input = user_input
    
    # PII Scrubbing
    phone_pattern = r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    address_pattern = r'\b\d+\s+[A-Za-z0-9\s,]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way)\b'
    
    scrubbed_input = re.sub(phone_pattern, "[REDACTED PHONE]", scrubbed_input)
    scrubbed_input = re.sub(ssn_pattern, "[REDACTED SSN]", scrubbed_input)
    scrubbed_input = re.sub(address_pattern, "[REDACTED ADDRESS]", scrubbed_input)
    
    pii_scrubbed = scrubbed_input != user_input
    
    # Prompt injection detection
    injection_keywords = ["ignore previous instructions", "system prompt", "bypass", "override", "you are now", "developer mode"]
    has_injection = any(kw in user_input.lower() for kw in injection_keywords)
    
    # Safety content filter
    harmful_keywords = ["kill myself", "suicide", "harm myself", "double dose", "overdose", "stop all medications"]
    has_harmful = any(kw in user_input.lower() for kw in harmful_keywords)
    
    if has_injection:
        log_audit_event("CRITICAL", "PROMPT_INJECTION", {"input": user_input})
        return Event(output="Security Warning: Potential prompt injection detected. Action blocked.", route="security_event")
        
    if has_harmful:
        log_audit_event("WARNING", "HARMFUL_CONTENT", {"input": user_input})
        return Event(output="Safety Warning: We noticed a command that could be unsafe. We cannot process requests regarding stopping medications, overdosing, or self-harm. Please contact your physician or a medical helpline immediately.", route="security_event")
    
    if pii_scrubbed:
        log_audit_event("INFO", "PII_REDACTED", {"original": user_input, "scrubbed": scrubbed_input})
        ctx.state["scrubbed_input"] = scrubbed_input
    else:
        log_audit_event("INFO", "SAFE_REQUEST", {"input": user_input})
        ctx.state["scrubbed_input"] = user_input
        
    return Event(output=scrubbed_input, route="__DEFAULT__")

def security_event_handler(node_input: Any) -> Event:
    """Handles security violations by returning safe feedback."""
    return Event(output=str(node_input))

# -----------------------------------------------------------------------------
# TOOL CALLBACKS (INTERCEPTS CRITICAL ACTIONS FOR HITL REVIEW)
# -----------------------------------------------------------------------------

async def after_tool_callback(tool, args: dict, tool_context, tool_response: dict) -> dict | None:
    """Intercepts tool calls to check if they need Human-in-the-Loop review."""
    tname = tool.name.lower()
    
    if "schedule_medication" in tname:
        is_crit = args.get("is_critical", False)
        if is_crit:
            tool_context.state["needs_approval"] = True
            tool_context.state["pending_action"] = {
                "type": "schedule_medication",
                "args": args
            }
            # Override tool response to inform sub-agent
            return {
                "status": "pending_approval",
                "message": f"Medication schedule for critical drug '{args.get('name')}' is flagged for confirmation."
            }
            
    elif "record_wellness_check" in tname:
        hr = int(args.get("heart_rate", 80))
        pain = int(args.get("pain_level", 0))
        if hr > 120 or hr < 50 or pain >= 7:
            tool_context.state["needs_approval"] = True
            tool_context.state["pending_action"] = {
                "type": "record_wellness_check",
                "args": args
            }
            # Override tool response to inform sub-agent
            return {
                "status": "pending_approval",
                "message": f"Wellness vitals check (heart rate {hr} bpm, pain {pain}/10) is flagged for critical review."
            }
            
    return None

# -----------------------------------------------------------------------------
# SUB-AGENTS & ORCHESTRATOR
# -----------------------------------------------------------------------------

medication_companion = LlmAgent(
    name="medication_companion",
    model=model_instance,
    instruction="You are a medication management assistant. Help users manage their medications, list schedules, and add new medication schedules. If a medication is life-critical, call schedule_medication with is_critical=True. Always describe the medication schedule to the user.",
    tools=[medication_tools],
    after_tool_callback=after_tool_callback
)

mental_gym_companion = LlmAgent(
    name="mental_gym_companion",
    model=model_instance,
    instruction="You are a wellness and mental exercises assistant. Help users with daily brain teasers, trivia, and recording their daily wellness checks (vitals, heart rate, pain level, mood). Always provide encouraging, friendly responses appropriate for elderly users.",
    tools=[wellness_tools],
    after_tool_callback=after_tool_callback
)

orchestrator = LlmAgent(
    name="orchestrator",
    model=model_instance,
    mode="single_turn",
    instruction="""You are the main coordinator for the Elderly Care Assistant. Your job is to address the user's needs by routing the conversation to either the Medication Companion (for medication schedules, medication additions, etc.) or the Mental Gym Companion (for brain teasers, puzzles, wellness vitals checks, etc.).
    
    If the user asks for a medication schedule or to add a new medication, call the Medication Companion tool.
    If the user asks for a puzzle, game, trivia, or wants to log a vitals check, call the Mental Gym Companion tool.
    
    Respond in a polite, warm, and clear tone suitable for an elderly person. If a sub-agent indicates an action is pending approval, tell the user that their request has been submitted for validation.""",
    tools=[AgentTool(medication_companion), AgentTool(mental_gym_companion)]
)

# -----------------------------------------------------------------------------
# ROUTING & HITL NODE IMPLEMENTATION
# -----------------------------------------------------------------------------

def process_response(ctx: Context, node_input: Any) -> Event:
    """Processes the orchestrator response and decides if we need HITL review."""
    text_content = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text_content = "".join([p.text for p in node_input.parts if p.text])
    elif isinstance(node_input, str):
        text_content = node_input
        
    ctx.state["orchestrator_response"] = text_content
    
    if ctx.state.get("needs_approval"):
        return Event(output=text_content, route="needs_approval")
    return Event(output=text_content, route="direct")

def human_approval(ctx: Context, node_input: Any):
    """Requests confirmation from the user for critical actions (HITL)."""
    if not ctx.resume_inputs:
        pending_action = ctx.state.get("pending_action", {})
        action_type = pending_action.get("type", "action")
        yield RequestInput(
            interrupt_id="approve_action",
            message=f"[HITL Review Required] You are performing a critical action ({action_type}). Please type 'Yes' to confirm and complete this, or 'No' to cancel."
        )
        return
        
    response = ctx.resume_inputs.get("approve_action", "").strip().lower()
    
    ctx.state["needs_approval"] = False
    pending_action = ctx.state.pop("pending_action", None)
    
    if response in ["yes", "y", "approve"]:
        msg = f"Action Approved: The critical request ({pending_action.get('type') if pending_action else 'action'}) has been successfully authorized and completed."
        yield Event(output=msg)
    else:
        msg = "Action Cancelled: The critical request has been declined and cancelled."
        yield Event(output=msg)

def format_final_output(ctx: Context, node_input: Any):
    """Formats the final text to display in the Web UI."""
    text = str(node_input)
    yield Event(
        content=types.Content(
            role='model',
            parts=[types.Part.from_text(text=text)]
        )
    )
    yield Event(output=text)

# -----------------------------------------------------------------------------
# WORKFLOW GRAPH DEFINITION
# -----------------------------------------------------------------------------

root_agent = Workflow(
    name="app",
    edges=[
        ('START', security_checkpoint),
        (security_checkpoint, {
            '__DEFAULT__': orchestrator,
            'security_event': security_event_handler
        }),
        (orchestrator, process_response),
        (process_response, {
            'needs_approval': human_approval,
            'direct': format_final_output
        }),
        (human_approval, format_final_output),
        (security_event_handler, format_final_output)
    ]
)

# Root App container
app = App(
    root_agent=root_agent,
    name="app"
)
