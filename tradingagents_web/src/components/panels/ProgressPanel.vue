<template>
  <div class="panel progress-panel">
    <div class="panel-header">进度</div>
    <div class="panel-body">
      <table v-if="store.displayAgentsByTeam.length > 0" class="progress-table">
        <thead>
          <tr>
            <th>团队</th>
            <th>代理</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(team, ti) in store.displayAgentsByTeam" :key="team.name">
            <tr v-for="(agent, ai) in team.agents" :key="agent">
              <td class="team-cell" v-if="ai === 0" :rowspan="team.agents.length">
                {{ team.name }}
              </td>
              <td class="agent-cell">{{ agent }}</td>
              <td class="status-cell">
                <AgentStatusBadge :status="store.agentStatuses[agent] || 'pending'" />
              </td>
            </tr>
            <tr v-if="ti < store.displayAgentsByTeam.length - 1" class="team-sep">
              <td colspan="3" />
            </tr>
          </template>
        </tbody>
      </table>

      <div v-else class="empty-state">
        等待分析开始...
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useAnalysisStore } from '../../stores/analysis'
import AgentStatusBadge from '../common/AgentStatusBadge.vue'

const store = useAnalysisStore()
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-right: 1px solid var(--border-color);
}

.panel-header {
  padding: var(--panel-padding);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-cyan);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.progress-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.progress-table th {
  text-align: left;
  padding: 4px 8px;
  color: var(--text-dim);
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border-subtle);
}

.progress-table td {
  padding: 6px 8px;
  vertical-align: middle;
}

.team-cell {
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 12px;
  white-space: nowrap;
  width: 100px;
}

.agent-cell {
  color: var(--text-primary);
}

.status-cell {
  text-align: right;
}

.team-sep td {
  height: 4px;
  border-bottom: 1px solid var(--border-subtle);
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-dim);
  font-size: 13px;
  font-style: italic;
}
</style>
