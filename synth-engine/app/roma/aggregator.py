"""Aggregator - Fourth stage of ROMA pipeline.

The Aggregator takes artifacts from all Executors and merges them
into a coherent WorkflowIR. It handles:
1. Resolving conflicts between executor outputs
2. Ensuring data contracts align across edges
3. Validating the combined workflow structure
4. Applying layout positions to all nodes
"""
from typing import Optional
from uuid import UUID

import structlog

logger = structlog.get_logger()

from app.models.workflow_ir import (
    WorkflowIR,
    StepSpec,
    StepType,
    TriggerType,
    EdgeSpec,
    AgentSpec,
    DataContract,
    FieldSchema,
    DataType,
    ErrorStrategy,
    RetryConfig,
    ErrorAction,
    TestInvariant,
    Position,
)
from app.models.task_tree import (
    TaskTree,
    Artifact,
    SubtaskType,
)

logger = structlog.get_logger()


class Aggregator:
    """Aggregator stage of the ROMA pipeline.
    
    Merges executor outputs into a single WorkflowIR.
    """
    
    def aggregate(
        self,
        tree: TaskTree,
        prompt: str,
    ) -> WorkflowIR:
        """Aggregate all artifacts into a WorkflowIR.
        
        Args:
            tree: TaskTree with completed tasks and artifacts
            prompt: Original user prompt
            
        Returns:
            Complete WorkflowIR ready for compilation
        """
        logger.info("aggregator_start", artifact_count=len(tree.get_all_artifacts()))
        
        # Collect artifacts by type
        artifacts = self._collect_artifacts(tree)
        
        # Build trigger
        trigger = self._build_trigger(artifacts)
        
        # Build steps (including agents)
        steps = self._build_steps(artifacts)
        
        # Ensure webhook workflows have a Respond to Webhook step
        if trigger.trigger_type == TriggerType.WEBHOOK:
            steps = self._ensure_respond_to_webhook(steps)
        
        # Build edges
        edges = self._build_edges(artifacts, trigger, steps)
        
        # Fix branching topology (LLM often gets this wrong)
        edges = self._fix_branching_topology(trigger, steps, edges)
        
        # Ensure all steps are reachable - fix missing edges
        edges = self._ensure_reachability(trigger, steps, edges)
        
        # Build error strategy
        error_strategy = self._build_error_strategy(artifacts)
        
        # Build success criteria from tests
        success_criteria = self._build_success_criteria(artifacts)
        
        # Apply layout positions
        self._apply_positions(artifacts, trigger, steps)
        
        # Generate workflow name
        name = self._generate_name(prompt)
        
        workflow_ir = WorkflowIR(
            name=name,
            description=prompt[:500],
            trigger=trigger,
            steps=steps,
            edges=edges,
            error_strategy=error_strategy,
            success_criteria=success_criteria,
            metadata={
                "original_prompt": prompt,
                "artifact_count": len(tree.get_all_artifacts()),
            },
        )
        
        logger.info(
            "aggregator_complete",
            step_count=len(steps),
            edge_count=len(edges),
        )
        
        return workflow_ir
    
    def _collect_artifacts(self, tree: TaskTree) -> dict[SubtaskType, list[Artifact]]:
        """Collect and group artifacts by type."""
        
        artifacts_by_type: dict[SubtaskType, list[Artifact]] = {}
        
        for artifact in tree.get_all_artifacts():
            if artifact.type not in artifacts_by_type:
                artifacts_by_type[artifact.type] = []
            artifacts_by_type[artifact.type].append(artifact)
        
        return artifacts_by_type
    
    def _build_trigger(self, artifacts: dict) -> StepSpec:
        """Build the trigger step from artifacts."""
        
        trigger_artifacts = artifacts.get(SubtaskType.CHOOSE_TRIGGER, [])
        
        # Default trigger config
        trigger_type = TriggerType.WEBHOOK
        n8n_type = "n8n-nodes-base.webhook"
        config = {"httpMethod": "POST", "path": "webhook"}
        
        if trigger_artifacts:
            trigger_data = trigger_artifacts[0].content
            type_str = trigger_data.get("trigger_type", "webhook")
            
            if type_str == "manual":
                trigger_type = TriggerType.MANUAL
                n8n_type = "n8n-nodes-base.manualTrigger"
                config = {}
            elif type_str == "schedule":
                trigger_type = TriggerType.SCHEDULE
                n8n_type = "n8n-nodes-base.scheduleTrigger"
                config = trigger_data.get("config", {})
            else:
                config = trigger_data.get("config", config)
        
        return StepSpec(
            id="trigger",
            name="Trigger",
            type=StepType.TRIGGER,
            n8n_node_type=n8n_type,
            trigger_type=trigger_type,
            trigger_config=config,
            parameters=config,
            position=Position(x=0, y=300),
        )
    
    def _build_steps(self, artifacts: dict) -> list[StepSpec]:
        """Build workflow steps from artifacts."""
        
        steps = []
        
        # Get node selections
        node_artifacts = artifacts.get(SubtaskType.SELECT_N8N_NODES, [])
        agent_artifacts = artifacts.get(SubtaskType.DEFINE_AGENTS, [])
        
        # Build agent lookup
        agents_by_name = {}
        for artifact in agent_artifacts:
            for agent_data in artifact.content.get("agents", []):
                agents_by_name[agent_data["name"]] = agent_data
        
        # Build steps from node selections
        if node_artifacts:
            selections = node_artifacts[0].content.get("node_selections", [])
            
            for i, selection in enumerate(selections):
                # Skip trigger (already handled)
                if selection.get("step_type") == "trigger":
                    continue
                
                step_type = self._map_step_type(selection.get("step_type", "action"))
                
                # Build agent spec if this is an agent step
                agent = None
                if step_type == StepType.AGENT:
                    agent_name = selection.get("agent_name", selection.get("step_id"))
                    if agent_name in agents_by_name:
                        agent = self._build_agent_spec(agents_by_name[agent_name])
                    else:
                        # Create a default agent
                        agent = AgentSpec(
                            name=agent_name,
                            role=selection.get("step_name", "Process data"),
                            tools_allowed=[],
                            input_schema=DataContract(
                                name=f"{agent_name}_input",
                                fields=[FieldSchema(name="input", type=DataType.OBJECT)],
                            ),
                            output_schema=DataContract(
                                name=f"{agent_name}_output",
                                fields=[FieldSchema(name="output", type=DataType.OBJECT)],
                            ),
                        )
                
                step = StepSpec(
                    id=selection.get("step_id", f"step_{i}"),
                    name=selection.get("step_name", f"Step {i + 1}"),
                    type=step_type,
                    n8n_node_type=selection.get("n8n_node_type", "n8n-nodes-base.set"),
                    n8n_type_version=selection.get("n8n_type_version", 1),
                    parameters=selection.get("parameters", {}),
                    agent=agent,
                    branch_conditions=selection.get("branch_conditions"),
                    position=Position(x=300 + (i * 250), y=300),
                )
                steps.append(step)
        
        return steps
    
    def _ensure_respond_to_webhook(self, steps: list[StepSpec]) -> list[StepSpec]:
        """Ensure webhook workflows have a Respond to Webhook step at the end."""
        
        # Check if we already have a respond to webhook step
        has_respond = any(
            s.n8n_node_type == "n8n-nodes-base.respondToWebhook" or
            "respondToWebhook" in s.name.lower() or
            "respond" in s.name.lower()
            for s in steps
        )
        
        if has_respond:
            return steps
        
        # Find the last step's position
        last_x = max((s.position.x for s in steps), default=300)
        last_y = 300
        
        # Create the respond to webhook step
        respond_step = StepSpec(
            id="respond_to_webhook",
            name="Respond to Webhook",
            type=StepType.ACTION,
            n8n_node_type="n8n-nodes-base.respondToWebhook",
            n8n_type_version=1,
            parameters={
                "respondWith": "json",
                "responseBody": "={{ $json }}",
            },
            position=Position(x=last_x + 250, y=last_y),
        )
        
        steps.append(respond_step)
        logger.info("added_respond_to_webhook", steps_count=len(steps))
        
        return steps
    
    def _build_agent_spec(self, agent_data: dict) -> AgentSpec:
        """Build an AgentSpec from artifact data."""
        
        input_schema = agent_data.get("input_schema", {})
        output_schema = agent_data.get("output_schema", {})
        
        return AgentSpec(
            name=agent_data.get("name", "agent"),
            role=agent_data.get("role", "Process data"),
            system_prompt=agent_data.get("system_prompt"),
            tools_allowed=agent_data.get("tools", []),
            input_schema=self._schema_to_data_contract(
                agent_data.get("name", "agent") + "_input",
                input_schema,
            ),
            output_schema=self._schema_to_data_contract(
                agent_data.get("name", "agent") + "_output",
                output_schema,
            ),
        )
    
    def _schema_to_data_contract(self, name: str, schema: dict) -> DataContract:
        """Convert JSON schema to DataContract."""
        
        fields = []
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        for prop_name, prop_def in properties.items():
            field_type = DataType.ANY
            type_str = prop_def.get("type", "any")
            if type_str == "string":
                field_type = DataType.STRING
            elif type_str == "number" or type_str == "integer":
                field_type = DataType.NUMBER
            elif type_str == "boolean":
                field_type = DataType.BOOLEAN
            elif type_str == "object":
                field_type = DataType.OBJECT
            elif type_str == "array":
                field_type = DataType.ARRAY
            
            fields.append(FieldSchema(
                name=prop_name,
                type=field_type,
                required=prop_name in required,
                description=prop_def.get("description"),
            ))
        
        return DataContract(name=name, fields=fields)
    
    def _map_step_type(self, type_str: str) -> StepType:
        """Map string step type to StepType enum."""
        
        mapping = {
            "trigger": StepType.TRIGGER,
            "action": StepType.ACTION,
            "agent": StepType.AGENT,
            "branch": StepType.BRANCH,
            "merge": StepType.MERGE,
            "transform": StepType.TRANSFORM,
        }
        return mapping.get(type_str, StepType.ACTION)
    
    def _build_edges(
        self,
        artifacts: dict,
        trigger: StepSpec,
        steps: list[StepSpec],
    ) -> list[EdgeSpec]:
        """Build edges from data contracts and node selections."""
        
        edges = []
        
        # Build ID mapping: various possible names -> actual step ID
        id_map = {
            "trigger": trigger.id,
            trigger.id: trigger.id,
            trigger.name.lower(): trigger.id,
            "webhook": trigger.id,
            "webhook_trigger": trigger.id,
        }
        
        for step in steps:
            id_map[step.id] = step.id
            id_map[step.name.lower()] = step.id
            # Also map by partial name matches
            name_parts = step.name.lower().replace("_", " ").replace("-", " ").split()
            for part in name_parts:
                if len(part) > 3:  # Only meaningful parts
                    id_map[part] = step.id
            if step.agent:
                id_map[step.agent.name.lower()] = step.id
        
        def resolve_step_id(step_ref: str) -> Optional[str]:
            """Resolve a step reference to actual step ID."""
            if not step_ref:
                return None
            ref_lower = step_ref.lower()
            # Direct match
            if ref_lower in id_map:
                return id_map[ref_lower]
            # Partial match
            for key, val in id_map.items():
                if key in ref_lower or ref_lower in key:
                    return val
            return None
        
        # Get data contracts
        contract_artifacts = artifacts.get(SubtaskType.DEFINE_DATA_CONTRACTS, [])
        
        if contract_artifacts:
            contracts = contract_artifacts[0].content.get("contracts", [])
            
            for contract in contracts:
                from_ref = contract.get("from_step", "trigger")
                to_ref = contract.get("to_step")
                
                if not to_ref:
                    continue
                
                from_step = resolve_step_id(from_ref)
                to_step = resolve_step_id(to_ref)
                
                if not from_step or not to_step:
                    logger.warning(
                        "unresolved_edge",
                        from_ref=from_ref,
                        to_ref=to_ref,
                        from_resolved=from_step,
                        to_resolved=to_step,
                    )
                    continue
                
                edge = EdgeSpec(
                    source_id=from_step,
                    target_id=to_step,
                    data_contract=self._schema_to_data_contract(
                        contract.get("name", f"{from_step}_to_{to_step}"),
                        contract.get("schema", {}),
                    ),
                    transform_expression=contract.get("transform"),
                    label=contract.get("name"),
                )
                edges.append(edge)
        
        # Always ensure edges exist - create topology-aware edges
        if not edges and steps:
            edges = self._build_topology_aware_edges(trigger, steps)
        
        return edges
    
    def _fix_branching_topology(
        self,
        trigger: StepSpec,
        steps: list[StepSpec],
        edges: list[EdgeSpec],
    ) -> list[EdgeSpec]:
        """Fix branching topology when LLM generates incorrect linear edges.
        
        Detects branch nodes and ensures they fan-out correctly.
        """
        if not steps:
            return edges
        
        # Find branch and merge nodes
        branch_nodes = [(i, s) for i, s in enumerate(steps) if s.type == StepType.BRANCH]
        merge_nodes = [(i, s) for i, s in enumerate(steps) if s.type == StepType.MERGE]
        
        if not branch_nodes:
            return edges  # No branching, nothing to fix
        
        logger.info(
            "fixing_branching_topology",
            branch_count=len(branch_nodes),
            merge_count=len(merge_nodes),
        )
        
        # For each branch node, check if it fans out correctly
        new_edges = []
        edges_to_remove = set()
        
        for branch_idx, branch_node in branch_nodes:
            # Find outgoing edges from branch node
            branch_outgoing = [e for e in edges if e.source_id == branch_node.id]
            
            # Find the next merge node (if any)
            merge_idx = None
            merge_node = None
            for mi, ms in merge_nodes:
                if mi > branch_idx:
                    merge_idx = mi
                    merge_node = ms
                    break
            
            # Find nodes between branch and merge that should be parallel
            if merge_idx:
                parallel_candidates = steps[branch_idx + 1:merge_idx]
            else:
                # No merge - nodes after branch until end are parallel
                parallel_candidates = steps[branch_idx + 1:]
            
            # Check if topology is already correct (branch fans out to multiple targets)
            if len(branch_outgoing) >= len(parallel_candidates) and len(parallel_candidates) > 1:
                continue  # Already correct
            
            # Remove incorrect linear edges between parallel candidates
            parallel_ids = {s.id for s in parallel_candidates}
            for edge in edges:
                if edge.source_id in parallel_ids and edge.target_id in parallel_ids:
                    edges_to_remove.add(edge.id)
            
            # Create fan-out edges from branch to each parallel node
            conditions = branch_node.branch_conditions or []
            for i, parallel_node in enumerate(parallel_candidates):
                condition_name = None
                if i < len(conditions):
                    condition_name = conditions[i].get("name") or conditions[i].get("value")
                
                new_edges.append(EdgeSpec(
                    source_id=branch_node.id,
                    target_id=parallel_node.id,
                    source_output=f"output{i}",
                    condition=condition_name,
                ))
            
            # Create fan-in edges to merge (if exists)
            if merge_node:
                for parallel_node in parallel_candidates:
                    # Check if edge already exists
                    existing = any(
                        e.source_id == parallel_node.id and e.target_id == merge_node.id
                        for e in edges
                    )
                    if not existing:
                        new_edges.append(EdgeSpec(
                            source_id=parallel_node.id,
                            target_id=merge_node.id,
                        ))
        
        # Filter out removed edges and add new ones
        fixed_edges = [e for e in edges if e.id not in edges_to_remove]
        
        # Avoid duplicates
        existing_pairs = {(e.source_id, e.target_id) for e in fixed_edges}
        for new_edge in new_edges:
            if (new_edge.source_id, new_edge.target_id) not in existing_pairs:
                fixed_edges.append(new_edge)
                existing_pairs.add((new_edge.source_id, new_edge.target_id))
        
        logger.info(
            "branching_topology_fixed",
            original_edges=len(edges),
            removed_edges=len(edges_to_remove),
            added_edges=len(new_edges),
            final_edges=len(fixed_edges),
        )
        
        return fixed_edges
    
    def _build_topology_aware_edges(
        self,
        trigger: StepSpec,
        steps: list[StepSpec],
    ) -> list[EdgeSpec]:
        """Build edges that respect branching and merging topology.
        
        Properly handles:
        - Branch nodes: fan-out to multiple targets
        - Merge nodes: fan-in from multiple sources
        - Linear nodes: single connection
        """
        edges = []
        
        if not steps:
            return edges
        
        # Find branch and merge nodes
        branch_nodes = [s for s in steps if s.type == StepType.BRANCH]
        merge_nodes = [s for s in steps if s.type == StepType.MERGE]
        other_nodes = [s for s in steps if s.type not in (StepType.BRANCH, StepType.MERGE)]
        
        # Trigger -> first step
        edges.append(EdgeSpec(
            source_id=trigger.id,
            target_id=steps[0].id,
        ))
        
        # Simple case: no branching, just chain
        if not branch_nodes:
            for i in range(len(steps) - 1):
                edges.append(EdgeSpec(
                    source_id=steps[i].id,
                    target_id=steps[i + 1].id,
                ))
            return edges
        
        # Complex case: handle branching topology
        # Strategy: 
        # 1. Pre-branch nodes chain linearly
        # 2. Branch node fans out to parallel paths
        # 3. Parallel paths converge at merge node
        # 4. Post-merge nodes chain linearly
        
        # Find the branch node position
        branch_idx = next(i for i, s in enumerate(steps) if s.type == StepType.BRANCH)
        
        # Chain pre-branch nodes
        for i in range(branch_idx):
            edges.append(EdgeSpec(
                source_id=steps[i].id,
                target_id=steps[i + 1].id,
            ))
        
        branch_node = steps[branch_idx]
        
        # Find merge node (if exists)
        merge_idx = None
        for i, s in enumerate(steps):
            if s.type == StepType.MERGE and i > branch_idx:
                merge_idx = i
                break
        
        # Find parallel path nodes (between branch and merge)
        if merge_idx:
            parallel_nodes = steps[branch_idx + 1:merge_idx]
            post_merge_nodes = steps[merge_idx + 1:]
            merge_node = steps[merge_idx]
        else:
            # No merge - all remaining nodes are parallel paths ending at last node
            parallel_nodes = steps[branch_idx + 1:-1] if len(steps) > branch_idx + 2 else []
            post_merge_nodes = [steps[-1]] if len(steps) > branch_idx + 1 else []
            merge_node = steps[-1] if steps else None
        
        # Fan-out from branch to parallel nodes
        conditions = branch_node.branch_conditions or []
        for i, parallel_node in enumerate(parallel_nodes):
            condition = conditions[i]["name"] if i < len(conditions) and "name" in conditions[i] else None
            edges.append(EdgeSpec(
                source_id=branch_node.id,
                target_id=parallel_node.id,
                source_output=f"output{i}",
                condition=condition,
            ))
        
        # If no parallel nodes but we have a merge, connect branch directly to merge
        if not parallel_nodes and merge_node and merge_node.id != branch_node.id:
            edges.append(EdgeSpec(
                source_id=branch_node.id,
                target_id=merge_node.id,
            ))
        
        # Fan-in from parallel nodes to merge
        if merge_node and parallel_nodes:
            for parallel_node in parallel_nodes:
                edges.append(EdgeSpec(
                    source_id=parallel_node.id,
                    target_id=merge_node.id,
                ))
        
        # Chain post-merge nodes
        if post_merge_nodes and merge_node:
            edges.append(EdgeSpec(
                source_id=merge_node.id,
                target_id=post_merge_nodes[0].id,
            ))
            for i in range(len(post_merge_nodes) - 1):
                edges.append(EdgeSpec(
                    source_id=post_merge_nodes[i].id,
                    target_id=post_merge_nodes[i + 1].id,
                ))
        
        return edges
    
    def _ensure_reachability(
        self,
        trigger: StepSpec,
        steps: list[StepSpec],
        edges: list[EdgeSpec],
    ) -> list[EdgeSpec]:
        """Ensure all steps are reachable from the trigger.
        
        For any unreachable steps, create edges to connect them.
        """
        if not steps:
            return edges
        
        # Track which steps have incoming edges
        has_incoming = set()
        for edge in edges:
            has_incoming.add(edge.target_id)
        
        # Track which steps are reachable via BFS
        reachable = {trigger.id}
        edge_sources = {}
        for edge in edges:
            if edge.source_id not in edge_sources:
                edge_sources[edge.source_id] = []
            edge_sources[edge.source_id].append(edge.target_id)
        
        queue = [trigger.id]
        while queue:
            current = queue.pop(0)
            for target in edge_sources.get(current, []):
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        
        # Find unreachable steps
        unreachable = [s for s in steps if s.id not in reachable]
        
        if unreachable:
            logger.warning(
                "fixing_unreachable_steps",
                unreachable_count=len(unreachable),
                unreachable_ids=[s.id for s in unreachable],
            )
            
            # Connect unreachable steps
            # Strategy: connect to trigger if no edges, or to last reachable step
            last_reachable = trigger.id
            for step in steps:
                if step.id in reachable:
                    last_reachable = step.id
            
            for step in unreachable:
                # Create edge from last reachable to this step
                edges.append(EdgeSpec(
                    source_id=last_reachable,
                    target_id=step.id,
                    label=f"auto_{last_reachable}_to_{step.id}",
                ))
                # Update tracking
                reachable.add(step.id)
                last_reachable = step.id
        
        return edges
    
    def _build_error_strategy(self, artifacts: dict) -> ErrorStrategy:
        """Build error strategy from artifacts."""
        
        error_artifacts = artifacts.get(SubtaskType.DEFINE_ERROR_HANDLING, [])
        
        if not error_artifacts:
            return ErrorStrategy()
        
        error_data = error_artifacts[0].content.get("error_strategy", {})
        
        action_str = error_data.get("default_action", "retry")
        action = ErrorAction.RETRY
        if action_str == "fallback":
            action = ErrorAction.FALLBACK
        elif action_str == "abort":
            action = ErrorAction.ABORT
        elif action_str == "continue":
            action = ErrorAction.CONTINUE
        
        retry_config = None
        if error_data.get("retry_config"):
            rc = error_data["retry_config"]
            retry_config = RetryConfig(
                max_retries=rc.get("max_retries", 3),
                backoff_ms=rc.get("backoff_ms", 1000),
                backoff_multiplier=rc.get("backoff_multiplier", 2.0),
            )
        
        return ErrorStrategy(
            default_action=action,
            retry_config=retry_config,
        )
    
    def _build_success_criteria(self, artifacts: dict) -> list[TestInvariant]:
        """Build success criteria from test artifacts."""
        
        test_artifacts = artifacts.get(SubtaskType.GENERATE_TESTS, [])
        
        criteria = []
        
        if test_artifacts:
            tests = test_artifacts[0].content.get("tests", [])
            
            for test in tests:
                for invariant in test.get("invariants", []):
                    criteria.append(TestInvariant(
                        name=f"{test['name']}_{invariant['type']}",
                        description=test.get("description", ""),
                        type=invariant.get("type", "execution_success"),
                        config={
                            **invariant.get("config", {}),
                            "test_name": test["name"],
                            "test_input": test.get("input"),
                            "expected_output": test.get("expected_output"),
                        },
                    ))
        
        return criteria
    
    def _apply_positions(
        self,
        artifacts: dict,
        trigger: StepSpec,
        steps: list[StepSpec],
    ) -> None:
        """Apply layout positions to all nodes.
        
        Uses topology-aware layout for branching workflows.
        """
        layout_artifacts = artifacts.get(SubtaskType.DEFINE_LAYOUT, [])
        
        if layout_artifacts:
            positions = layout_artifacts[0].content.get("positions", {})
            
            if "trigger" in positions:
                pos = positions["trigger"]
                trigger.position = Position(x=pos["x"], y=pos["y"])
            
            for step in steps:
                if step.id in positions:
                    pos = positions[step.id]
                    step.position = Position(x=pos["x"], y=pos["y"])
        
        # Always apply topology-aware layout to fix positions for branching
        self._apply_topology_layout(trigger, steps)
    
    def _apply_topology_layout(
        self,
        trigger: StepSpec,
        steps: list[StepSpec],
    ) -> None:
        """Apply automatic layout that respects branching topology."""
        
        X_SPACING = 300
        Y_SPACING = 180
        BASE_Y = 300
        
        trigger.position = Position(x=0, y=BASE_Y)
        
        if not steps:
            return
        
        # Find branch and merge indices
        branch_idx = None
        merge_idx = None
        for i, s in enumerate(steps):
            if s.type == StepType.BRANCH and branch_idx is None:
                branch_idx = i
            if s.type == StepType.MERGE and merge_idx is None and (branch_idx is not None):
                merge_idx = i
        
        if branch_idx is None:
            # Simple linear layout
            for i, step in enumerate(steps):
                step.position = Position(x=(i + 1) * X_SPACING, y=BASE_Y)
            return
        
        # Branching layout
        x_pos = X_SPACING
        
        # Pre-branch nodes (linear)
        for i in range(branch_idx):
            steps[i].position = Position(x=x_pos, y=BASE_Y)
            x_pos += X_SPACING
        
        # Branch node
        steps[branch_idx].position = Position(x=x_pos, y=BASE_Y)
        x_pos += X_SPACING
        
        # Determine parallel nodes and convergence point
        if merge_idx:
            parallel_nodes = steps[branch_idx + 1:merge_idx]
            convergence_idx = merge_idx
            post_convergence = steps[merge_idx:]
        else:
            # No explicit merge - treat last node as convergence point
            # Parallel nodes are everything between branch and last node
            if len(steps) > branch_idx + 2:
                parallel_nodes = steps[branch_idx + 1:-1]
                convergence_idx = len(steps) - 1
                post_convergence = [steps[-1]]
            else:
                # Not enough nodes for branching layout
                parallel_nodes = steps[branch_idx + 1:]
                convergence_idx = None
                post_convergence = []
        
        # Layout parallel nodes (spread vertically)
        parallel_count = len(parallel_nodes)
        if parallel_count > 0:
            # Center the parallel nodes vertically around BASE_Y
            total_height = (parallel_count - 1) * Y_SPACING
            start_y = BASE_Y - total_height / 2
            
            for i, node in enumerate(parallel_nodes):
                node.position = Position(x=x_pos, y=int(start_y + i * Y_SPACING))
            
            x_pos += X_SPACING
        
        # Convergence/merge node and post-convergence
        for step in post_convergence:
            step.position = Position(x=x_pos, y=BASE_Y)
            x_pos += X_SPACING
    
    def _generate_name(self, prompt: str) -> str:
        """Generate a workflow name from the prompt."""
        
        # Take first sentence or first 50 chars
        name = prompt.split(".")[0][:50]
        
        # Clean up
        name = " ".join(name.split())
        
        if len(name) < 5:
            name = "Generated Workflow"
        
        return name
