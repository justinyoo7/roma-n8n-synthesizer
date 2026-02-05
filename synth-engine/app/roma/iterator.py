"""Iterator - LLM-based fix generation for failed workflows.

The Iterator analyzes test failures and generates fixes:
1. Parse failure traces to identify root causes
2. Use LLM to propose specific fixes
3. Apply fixes to WorkflowIR
4. Return updated workflow for re-testing
"""
from typing import Optional
from uuid import UUID, uuid4

import structlog

from app.llm.adapter import get_llm_adapter, generate_with_logging
from app.models.workflow_ir import (
    WorkflowIR,
    StepSpec,
    EdgeSpec,
    StepType,
    Position,
)
from app.models.task_tree import FixPlan
from app.testing.harness import TestResult

logger = structlog.get_logger()


# System prompt for failure analysis
FAILURE_ANALYSIS_PROMPT = """You are a workflow debugging expert. Analyze the following test failures and identify the root causes.

For each failure, determine:
1. Which node/step is likely causing the issue
2. What type of fix is needed (parameter change, node replacement, edge fix, etc.)
3. The specific change to make

Respond with JSON:
{{
    "analysis": [
        {{
            "failure_index": 0,
            "root_cause": "Brief description of root cause",
            "affected_step_id": "step_id or null",
            "fix_type": "parameter_change|node_replacement|edge_fix|add_node|remove_node|restructure",
            "fix_details": {{
                "description": "What to change",
                "new_value": "If applicable, the new value"
            }}
        }}
    ],
    "requires_major_restructure": false,
    "summary": "Overall assessment of what's wrong"
}}"""


# System prompt for fix generation
FIX_GENERATION_PROMPT = """You are a workflow repair expert. Given the original workflow and the identified issues, generate specific fixes.

For parameter changes, provide the exact new parameter values.
For node replacements, provide the new node type and parameters.
For edge fixes, specify which edges to add/remove/modify.

Original workflow:
{workflow_json}

Identified issues:
{issues_json}

Respond with JSON containing the fixes to apply:
{{
    "fixes": [
        {{
            "step_id": "The step to modify (or null for new steps)",
            "action": "update_parameters|replace_node|add_edge|remove_edge|add_step|remove_step",
            "parameters": {{}},
            "new_node_type": "",
            "edge": {{"source_id": "", "target_id": ""}},
            "new_step": {{}}
        }}
    ],
    "explanation": "Why these fixes should work"
}}"""


class Iterator:
    """Iterates on workflows based on test failures."""
    
    def __init__(self):
        self.llm = get_llm_adapter()
    
    async def analyze_failures(
        self,
        workflow_ir: WorkflowIR,
        test_results: list[TestResult],
        n8n_errors: list[str],
        workflow_id: Optional[UUID] = None,
    ) -> dict:
        """Analyze test failures and n8n errors to identify root causes.
        
        Args:
            workflow_ir: The workflow that failed
            test_results: List of test results (including failures)
            n8n_errors: Any errors from n8n execution
            workflow_id: Optional workflow ID for tracking
            
        Returns:
            Analysis dict with root causes and suggested fix types
        """
        # Build failure context
        failures = []
        
        for i, result in enumerate(test_results):
            if not result.passed:
                failures.append({
                    "index": i,
                    "test_name": result.test_name,
                    "input": result.input_payload,
                    "expected": result.expected_output,
                    "actual": result.actual_output,
                    "error": result.failure_reason,
                    "checkpoints": result.checkpoints,
                })
        
        for error in n8n_errors:
            failures.append({
                "index": len(failures),
                "type": "n8n_error",
                "error": error,
            })
        
        if not failures:
            return {"analysis": [], "requires_major_restructure": False, "summary": "No failures"}
        
        # Build workflow summary for context
        workflow_summary = {
            "name": workflow_ir.name,
            "trigger": {
                "id": workflow_ir.trigger.id,
                "type": workflow_ir.trigger.type.value,
                "n8n_type": workflow_ir.trigger.n8n_node_type,
            },
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.type.value,
                    "n8n_type": s.n8n_node_type,
                }
                for s in workflow_ir.steps
            ],
            "edges": [
                {"from": e.source_id, "to": e.target_id}
                for e in workflow_ir.edges
            ],
        }
        
        # Call LLM for analysis
        import json
        prompt = f"""Workflow structure:
{json.dumps(workflow_summary, indent=2)}

Test failures:
{json.dumps(failures, indent=2)}

Analyze these failures and identify root causes."""

        try:
            response = await generate_with_logging(
                system_prompt=FAILURE_ANALYSIS_PROMPT,
                user_message=prompt,
                node_name="Iterator - Failure Analysis",
                response_format="json",
                workflow_id=workflow_id,
            )
            
            # LLMResponse.content is already parsed for JSON format
            analysis = response.content
            
            # Handle case where parsing failed in the LLM adapter
            if isinstance(analysis, dict) and "error" in analysis:
                logger.warning("failure_analysis_json_error", error=analysis.get("error"))
                raise ValueError(f"LLM returned invalid JSON")
            
            # If content is still a string, try to extract JSON from it
            if isinstance(analysis, str):
                analysis_str = analysis.strip()
                
                # Look for JSON object pattern
                start_idx = analysis_str.find('{')
                end_idx = analysis_str.rfind('}')
                
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_str = analysis_str[start_idx:end_idx + 1]
                    try:
                        analysis = json.loads(json_str)
                    except json.JSONDecodeError as e:
                        logger.warning("failure_analysis_json_extract_failed", error=str(e))
                        raise ValueError("Failed to parse LLM JSON response")
                else:
                    raise ValueError("No valid JSON found in LLM response")
            
            # Ensure we have a dict
            if not isinstance(analysis, dict):
                raise ValueError(f"Expected dict, got {type(analysis).__name__}")
            
            logger.info(
                "failure_analysis_complete",
                failure_count=len(failures),
                fix_count=len(analysis.get("analysis", [])),
            )
            return analysis
            
        except Exception as e:
            import traceback
            logger.error(
                "failure_analysis_error", 
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc()
            )
            # Return basic analysis on error
            return {
                "analysis": [
                    {
                        "failure_index": 0,
                        "root_cause": "Unknown - analysis failed",
                        "affected_step_id": None,
                        "fix_type": "restructure",
                        "fix_details": {"description": "Re-generate workflow"},
                    }
                ],
                "requires_major_restructure": True,
                "summary": f"Analysis failed: {str(e)}",
            }
    
    async def generate_fixes(
        self,
        workflow_ir: WorkflowIR,
        analysis: dict,
        workflow_id: Optional[UUID] = None,
    ) -> list[dict]:
        """Generate specific fixes based on failure analysis.
        
        Args:
            workflow_ir: The workflow to fix
            analysis: Analysis from analyze_failures()
            workflow_id: Optional workflow ID for tracking
            
        Returns:
            List of fix operations to apply
        """
        import json
        
        # Build workflow JSON for context
        workflow_json = {
            "name": workflow_ir.name,
            "trigger": {
                "id": workflow_ir.trigger.id,
                "name": workflow_ir.trigger.name,
                "type": workflow_ir.trigger.type.value,
                "n8n_type": workflow_ir.trigger.n8n_node_type,
                "parameters": workflow_ir.trigger.parameters,
            },
            "steps": [
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.type.value,
                    "n8n_type": s.n8n_node_type,
                    "parameters": s.parameters,
                }
                for s in workflow_ir.steps
            ],
        }
        
        prompt = FIX_GENERATION_PROMPT.format(
            workflow_json=json.dumps(workflow_json, indent=2),
            issues_json=json.dumps(analysis, indent=2),
        )
        
        try:
            response = await generate_with_logging(
                system_prompt="You are a workflow repair expert. Generate specific fixes in JSON format.",
                user_message=prompt,
                node_name="Iterator - Fix Generation",
                response_format="json",
                workflow_id=workflow_id,
            )
            
            # LLMResponse.content is already parsed for JSON format
            fixes = response.content
            
            # Handle case where parsing failed in the LLM adapter
            if isinstance(fixes, dict) and "error" in fixes:
                logger.warning("fix_generation_json_error", error=fixes.get("error"))
                return []
            
            # If content is still a string, try to extract JSON from it
            if isinstance(fixes, str):
                # Try to find and extract JSON object
                fixes_str = fixes.strip()
                
                # Look for JSON object pattern
                start_idx = fixes_str.find('{')
                end_idx = fixes_str.rfind('}')
                
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_str = fixes_str[start_idx:end_idx + 1]
                    try:
                        fixes = json.loads(json_str)
                    except json.JSONDecodeError:
                        logger.warning("fix_generation_json_extract_failed", content=fixes_str[:200])
                        return []
                else:
                    logger.warning("fix_generation_no_json_found", content=fixes_str[:200])
                    return []
            
            # Ensure we have a dict with fixes key
            if not isinstance(fixes, dict):
                logger.warning("fix_generation_not_dict", type=type(fixes).__name__)
                return []
            
            logger.info(
                "fix_generation_complete",
                fix_count=len(fixes.get("fixes", [])),
            )
            return fixes.get("fixes", [])
            
        except Exception as e:
            import traceback
            logger.error(
                "fix_generation_error", 
                error=str(e),
                error_type=type(e).__name__,
                traceback=traceback.format_exc()
            )
            return []
    
    def apply_fixes(
        self,
        workflow_ir: WorkflowIR,
        fixes: list[dict],
    ) -> WorkflowIR:
        """Apply generated fixes to a WorkflowIR.
        
        Args:
            workflow_ir: The workflow to modify
            fixes: List of fixes from generate_fixes()
            
        Returns:
            Modified WorkflowIR
        """
        import copy
        
        # Deep copy to avoid modifying original
        modified = copy.deepcopy(workflow_ir)
        
        for fix in fixes:
            action = fix.get("action")
            step_id = fix.get("step_id")
            
            try:
                if action == "update_parameters":
                    self._apply_parameter_update(modified, step_id, fix.get("parameters", {}))
                    
                elif action == "replace_node":
                    self._apply_node_replacement(modified, step_id, fix)
                    
                elif action == "add_edge":
                    self._apply_add_edge(modified, fix.get("edge", {}))
                    
                elif action == "remove_edge":
                    self._apply_remove_edge(modified, fix.get("edge", {}))
                    
                elif action == "add_step":
                    self._apply_add_step(modified, fix.get("new_step", {}))
                    
                elif action == "remove_step":
                    self._apply_remove_step(modified, step_id)
                    
                logger.debug("fix_applied", action=action, step_id=step_id)
                
            except Exception as e:
                logger.error(
                    "fix_application_error",
                    action=action,
                    step_id=step_id,
                    error=str(e),
                )
        
        return modified
    
    def _apply_parameter_update(
        self,
        workflow_ir: WorkflowIR,
        step_id: str,
        new_parameters: dict,
    ) -> None:
        """Update parameters for a step."""
        if step_id == workflow_ir.trigger.id:
            workflow_ir.trigger.parameters.update(new_parameters)
        else:
            for step in workflow_ir.steps:
                if step.id == step_id:
                    step.parameters.update(new_parameters)
                    break
    
    def _apply_node_replacement(
        self,
        workflow_ir: WorkflowIR,
        step_id: str,
        fix: dict,
    ) -> None:
        """Replace a node with a different type."""
        new_type = fix.get("new_node_type")
        new_params = fix.get("parameters", {})
        
        for step in workflow_ir.steps:
            if step.id == step_id:
                step.n8n_node_type = new_type
                step.parameters = new_params
                break
    
    def _apply_add_edge(
        self,
        workflow_ir: WorkflowIR,
        edge: dict,
    ) -> None:
        """Add a new edge."""
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        
        if source_id and target_id:
            # Check if edge already exists
            existing = any(
                e.source_id == source_id and e.target_id == target_id
                for e in workflow_ir.edges
            )
            if not existing:
                workflow_ir.edges.append(EdgeSpec(
                    source_id=source_id,
                    target_id=target_id,
                ))
    
    def _apply_remove_edge(
        self,
        workflow_ir: WorkflowIR,
        edge: dict,
    ) -> None:
        """Remove an edge."""
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        
        workflow_ir.edges = [
            e for e in workflow_ir.edges
            if not (e.source_id == source_id and e.target_id == target_id)
        ]
    
    def _apply_add_step(
        self,
        workflow_ir: WorkflowIR,
        step_config: dict,
    ) -> None:
        """Add a new step."""
        step_id = step_config.get("id", str(uuid4())[:8])
        
        # Determine position based on existing steps
        max_x = max(
            (s.position.x for s in workflow_ir.steps),
            default=0
        )
        
        new_step = StepSpec(
            id=step_id,
            name=step_config.get("name", "New Step"),
            type=StepType(step_config.get("type", "action")),
            n8n_node_type=step_config.get("n8n_type", "n8n-nodes-base.set"),
            parameters=step_config.get("parameters", {}),
            position=Position(x=max_x + 300, y=300),
        )
        
        workflow_ir.steps.append(new_step)
    
    def _apply_remove_step(
        self,
        workflow_ir: WorkflowIR,
        step_id: str,
    ) -> None:
        """Remove a step and its connected edges."""
        # Remove the step
        workflow_ir.steps = [s for s in workflow_ir.steps if s.id != step_id]
        
        # Remove connected edges
        workflow_ir.edges = [
            e for e in workflow_ir.edges
            if e.source_id != step_id and e.target_id != step_id
        ]
    
    async def iterate(
        self,
        workflow_ir: WorkflowIR,
        test_results: list[TestResult],
        n8n_errors: list[str],
        iteration_number: int,
        workflow_id: Optional[UUID] = None,
    ) -> tuple[WorkflowIR, dict]:
        """Perform one iteration cycle: analyze -> generate fixes -> apply.
        
        Args:
            workflow_ir: Current workflow
            test_results: Test results from last run
            n8n_errors: n8n errors from last run
            iteration_number: Current iteration count
            workflow_id: Optional workflow ID for tracking
            
        Returns:
            Tuple of (modified WorkflowIR, iteration metadata)
        """
        logger.info(
            "iteration_start",
            iteration=iteration_number,
            test_failures=sum(1 for r in test_results if not r.passed),
            n8n_errors=len(n8n_errors),
        )
        
        # Step 1: Analyze failures
        analysis = await self.analyze_failures(workflow_ir, test_results, n8n_errors, workflow_id=workflow_id)
        
        # Step 2: Generate fixes
        fixes = await self.generate_fixes(workflow_ir, analysis, workflow_id=workflow_id)
        
        # Step 3: Apply fixes
        modified_ir = self.apply_fixes(workflow_ir, fixes)
        
        metadata = {
            "iteration": iteration_number,
            "analysis": analysis,
            "fixes_applied": len(fixes),
            "fixes": fixes,
            "requires_major_restructure": analysis.get("requires_major_restructure", False),
        }
        
        logger.info(
            "iteration_complete",
            iteration=iteration_number,
            fixes_applied=len(fixes),
        )
        
        return modified_ir, metadata
