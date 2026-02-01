-- ROMA Workflow Synthesizer Database Schema
-- Run this in your Supabase SQL editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Workflows table
-- Stores the main workflow records
CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    n8n_workflow_id TEXT,
    current_iteration_id UUID,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'testing', 'passing', 'deployed', 'failed')),
    original_prompt TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for user lookups
CREATE INDEX IF NOT EXISTS idx_workflows_user_id ON workflows(user_id);
CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
CREATE INDEX IF NOT EXISTS idx_workflows_created_at ON workflows(created_at DESC);

-- Iterations table
-- Stores each version of the workflow
CREATE TABLE IF NOT EXISTS iterations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    workflow_ir JSONB NOT NULL,
    n8n_json JSONB,
    rationale TEXT,
    score INTEGER CHECK (score >= 0 AND score <= 100),
    score_breakdown JSONB,
    fix_plan JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Ensure version numbers are unique per workflow
    UNIQUE(workflow_id, version)
);

-- Create indexes for iteration lookups
CREATE INDEX IF NOT EXISTS idx_iterations_workflow_id ON iterations(workflow_id);
CREATE INDEX IF NOT EXISTS idx_iterations_version ON iterations(workflow_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_iterations_score ON iterations(score DESC);

-- Test runs table
-- Stores results of test executions
CREATE TABLE IF NOT EXISTS test_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    iteration_id UUID NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
    test_name TEXT NOT NULL,
    test_type TEXT CHECK (test_type IN ('happy_path', 'error_handling', 'edge_case', 'custom')),
    input_payload JSONB,
    expected_output JSONB,
    actual_output JSONB,
    checkpoints JSONB,
    passed BOOLEAN NOT NULL,
    failure_reason TEXT,
    duration_ms INTEGER,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for test run lookups
CREATE INDEX IF NOT EXISTS idx_test_runs_iteration_id ON test_runs(iteration_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_passed ON test_runs(passed);

-- Artifacts table
-- Stores large artifacts from synthesis process
CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    iteration_id UUID NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN (
        'task_tree',
        'node_selection',
        'data_contract',
        'mapping',
        'test_case',
        'validation_result',
        'compilation_result',
        'simplification_result',
        'llm_trace'
    )),
    content JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for artifact lookups
CREATE INDEX IF NOT EXISTS idx_artifacts_iteration_id ON artifacts(iteration_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);

-- Agent run logs table
-- Stores logs from agent-runner executions
CREATE TABLE IF NOT EXISTS agent_run_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    iteration_id UUID REFERENCES iterations(id) ON DELETE SET NULL,
    agent_name TEXT NOT NULL,
    input_payload JSONB NOT NULL,
    output_payload JSONB,
    tools_used TEXT[],
    tokens_used INTEGER,
    duration_ms INTEGER,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for agent run lookups
CREATE INDEX IF NOT EXISTS idx_agent_run_logs_iteration_id ON agent_run_logs(iteration_id);
CREATE INDEX IF NOT EXISTS idx_agent_run_logs_agent_name ON agent_run_logs(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_run_logs_created_at ON agent_run_logs(created_at DESC);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for workflows table
DROP TRIGGER IF EXISTS update_workflows_updated_at ON workflows;
CREATE TRIGGER update_workflows_updated_at
    BEFORE UPDATE ON workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to auto-increment iteration version
CREATE OR REPLACE FUNCTION get_next_iteration_version(p_workflow_id UUID)
RETURNS INTEGER AS $$
DECLARE
    v_next_version INTEGER;
BEGIN
    SELECT COALESCE(MAX(version), 0) + 1 INTO v_next_version
    FROM iterations
    WHERE workflow_id = p_workflow_id;
    
    RETURN v_next_version;
END;
$$ language 'plpgsql';

-- Row Level Security (RLS) policies
-- Enable RLS on all tables
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE iterations ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_run_logs ENABLE ROW LEVEL SECURITY;

-- Policies for workflows
CREATE POLICY "Users can view their own workflows" ON workflows
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can create their own workflows" ON workflows
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own workflows" ON workflows
    FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete their own workflows" ON workflows
    FOR DELETE USING (auth.uid() = user_id);

-- Policies for iterations (access through workflow ownership)
CREATE POLICY "Users can view iterations of their workflows" ON iterations
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM workflows
            WHERE workflows.id = iterations.workflow_id
            AND workflows.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can create iterations for their workflows" ON iterations
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM workflows
            WHERE workflows.id = iterations.workflow_id
            AND workflows.user_id = auth.uid()
        )
    );

-- Policies for test_runs (access through iteration -> workflow ownership)
CREATE POLICY "Users can view test runs of their workflows" ON test_runs
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM iterations
            JOIN workflows ON workflows.id = iterations.workflow_id
            WHERE iterations.id = test_runs.iteration_id
            AND workflows.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can create test runs for their workflows" ON test_runs
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM iterations
            JOIN workflows ON workflows.id = iterations.workflow_id
            WHERE iterations.id = test_runs.iteration_id
            AND workflows.user_id = auth.uid()
        )
    );

-- Policies for artifacts
CREATE POLICY "Users can view artifacts of their workflows" ON artifacts
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM iterations
            JOIN workflows ON workflows.id = iterations.workflow_id
            WHERE iterations.id = artifacts.iteration_id
            AND workflows.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can create artifacts for their workflows" ON artifacts
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM iterations
            JOIN workflows ON workflows.id = iterations.workflow_id
            WHERE iterations.id = artifacts.iteration_id
            AND workflows.user_id = auth.uid()
        )
    );

-- Policies for agent_run_logs (access through iteration)
CREATE POLICY "Users can view agent logs of their workflows" ON agent_run_logs
    FOR SELECT USING (
        iteration_id IS NULL OR
        EXISTS (
            SELECT 1 FROM iterations
            JOIN workflows ON workflows.id = iterations.workflow_id
            WHERE iterations.id = agent_run_logs.iteration_id
            AND workflows.user_id = auth.uid()
        )
    );

CREATE POLICY "Users can create agent logs" ON agent_run_logs
    FOR INSERT WITH CHECK (true);

-- Service role bypass for backend operations
-- These policies allow the service role to access all data
CREATE POLICY "Service role can access all workflows" ON workflows
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role can access all iterations" ON iterations
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role can access all test_runs" ON test_runs
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role can access all artifacts" ON artifacts
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

CREATE POLICY "Service role can access all agent_run_logs" ON agent_run_logs
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');
