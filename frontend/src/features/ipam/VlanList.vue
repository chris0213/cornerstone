<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage, ElTree, ElDialog } from 'element-plus';
import { Plus, Edit, Delete } from '@element-plus/icons-vue';
import { applyKeywordFilter } from '../../lib/filters';
import { confirmAndRun } from '../../lib/confirm';

const { t } = useI18n();
import type { VlanGroup, Vlan, Prefix } from '../../types/domain';
import type { SiteResponse } from '../../api/sites';
import { 
  getVlanGroups, createVlanGroup, updateVlanGroup,
  getVlans, createVlan, updateVlan, deleteVlan,
  type VlanGroupResponse, type VlanResponse
} from '../../api/vlans';
import { getSites } from '../../api/sites';
import { getPrefixes } from '../../api/ipam';

const sites = ref<SiteResponse[]>([]);
const prefixes = ref<Prefix[]>([]);

function siteName(siteId: number | undefined): string {
  if (!siteId) return '-';
  return sites.value.find(s => s.id === siteId)?.name || '-';
}

const vlanGroups = ref<VlanGroup[]>([]);
const vlans = ref<Vlan[]>([]);

const activeGroupId = ref<number | null>(null);
const searchQuery = ref('');
const showGroupDialog = ref(false);
const showVlanDialog = ref(false);
const editingGroup = ref<VlanGroup | null>(null);
const editingVlan = ref<Vlan | null>(null);
const sidebarCollapsed = ref(false);
const groupForm = ref({
 id: 0,
 name: '',
 siteId: undefined as number | undefined,
 description: ''
});
const vlanForm = ref({
 id: 0,
 vid: 0,
 name: '',
 groupId: undefined as number | undefined,
 siteId: undefined as number | undefined,
 status: 'active',
 description: ''
});

const filteredVlans = computed(() => {
  let result = vlans.value;
  if (activeGroupId.value !== null) {
    result = result.filter(v => v.groupId === activeGroupId.value);
  }
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase();
    const rangeMatch = query.match(/^(\d+)-(\d+)$/);
    if (rangeMatch) {
      // VID 范围查询（如 10-20），业务特化逻辑保留
      const start = parseInt(rangeMatch[1]);
      const end = parseInt(rangeMatch[2]);
      result = result.filter(v => v.vid >= start && v.vid <= end);
    } else {
      result = applyKeywordFilter(result, searchQuery.value, ['vid', 'name']);
    }
  }
  return result;
});

const groupTreeData = computed(() => {
  const groups = vlanGroups.value.map(group => ({
    id: group.id.toString(),
    label: group.name,
    children: []
  }));
  return [
    {
      id: 'all',
      label: t('vlan.allVlans'),
      children: groups
    }
  ];
});

const resetGroupForm = () => {
  groupForm.value = {
    id: 0,
    name: '',
    siteId: undefined,
    description: ''
  };
  editingGroup.value = null;
};

const resetVlanForm = () => {
  vlanForm.value = {
    id: 0,
    vid: 0,
    name: '',
    groupId: activeGroupId.value || undefined,
    siteId: undefined,
    status: 'active',
    description: ''
  };
  editingVlan.value = null;
};

const openCreateGroupDialog = () => {
  resetGroupForm();
  showGroupDialog.value = true;
};

const openEditGroupDialog = (group: VlanGroup) => {
  editingGroup.value = group;
  groupForm.value = {
    id: group.id,
    name: group.name,
    siteId: group.siteId,
    description: group.description || ''
  };
  showGroupDialog.value = true;
};

const closeGroupDialog = () => {
  showGroupDialog.value = false;
  resetGroupForm();
};

const handleSaveGroup = async () => {
  if (!groupForm.value.name.trim()) {
    ElMessage.error(t('vlan.groupNameRequired'));
    return;
  }

  try {
    const data = {
      name: groupForm.value.name,
      site_id: groupForm.value.siteId || null,
      description: groupForm.value.description || null
    };

    if (editingGroup.value) {
      const response = await updateVlanGroup(editingGroup.value.id, data);
      const index = vlanGroups.value.findIndex(g => g.id === response.id);
      if (index !== -1) {
        vlanGroups.value[index] = convertToVlanGroup(response);
      }
      ElMessage.success(t('vlan.updateSuccess'));
    } else {
      const response = await createVlanGroup(data);
      vlanGroups.value.push(convertToVlanGroup(response));
      ElMessage.success(t('vlan.createSuccess'));
    }
    closeGroupDialog();
  } catch (error) {
    console.error('Failed to save VLAN group:', error);
    ElMessage.error(t('vlan.saveFailed'));
  }
};

const openCreateVlanDialog = () => {
  resetVlanForm();
  showVlanDialog.value = true;
};

const openEditVlanDialog = (vlan: Vlan) => {
  editingVlan.value = vlan;
  vlanForm.value = {
    id: vlan.id,
    vid: vlan.vid,
    name: vlan.name || '',
    groupId: vlan.groupId || undefined,
    siteId: vlan.siteId || undefined,
    status: vlan.status,
    description: vlan.description || ''
  };
  showVlanDialog.value = true;
};

const closeVlanDialog = () => {
  showVlanDialog.value = false;
  resetVlanForm();
};

const handleSaveVlan = async () => {
  if (!vlanForm.value.vid || vlanForm.value.vid < 1 || vlanForm.value.vid > 4094) {
    ElMessage.error(t('vlan.invalidVid'));
    return;
  }

  try {
    const data = {
      vid: vlanForm.value.vid,
      name: vlanForm.value.name || null,
      group_id: vlanForm.value.groupId || null,
      site_id: vlanForm.value.siteId || null,
      status: vlanForm.value.status,
      description: vlanForm.value.description || null
    };

    if (editingVlan.value) {
      const response = await updateVlan(editingVlan.value.id, data);
      const index = vlans.value.findIndex(v => v.id === response.id);
      if (index !== -1) {
        vlans.value[index] = convertToVlan(response);
      }
      ElMessage.success(t('vlan.vlanUpdateSuccess'));
    } else {
      const response = await createVlan(data);
      vlans.value.push(convertToVlan(response));
      ElMessage.success(t('vlan.vlanCreateSuccess'));
    }
    closeVlanDialog();
  } catch (error: any) {
    console.error('Failed to save VLAN:', error);
    const detail = error?.response?.data?.detail;
    if (detail) {
      ElMessage.error(detail);
    } else {
      ElMessage.error(t('vlan.vlanSaveFailed'));
    }
  }
};

const handleDeleteVlan = async (vlan: Vlan) => {
  await confirmAndRun({
    message: t('vlan.confirmDeleteVlan', { vid: vlan.vid }),
    title: t('common.confirmDelete'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    action: async () => {
      await deleteVlan(vlan.id);
      vlans.value = vlans.value.filter(v => v.id !== vlan.id);
    },
    successMessage: t('vlan.vlanDeleteSuccess'),
    errorMessage: t('vlan.vlanDeleteFailed'),
  });
};

const getStatusTag = (status: string) => {
  const tags: Record<string, { type: string; text: string }> = {
    active: { type: 'success', text: t('vlan.statusActive') },
    reserved: { type: 'warning', text: t('vlan.statusReserved') },
    deprecated: { type: 'danger', text: t('vlan.statusDeprecated') }
  };
  return tags[status] || { type: 'info', text: status };
};

const getRelatedPrefixes = (vid: number) => {
  return prefixes.value.filter(p => p.vlan === vid.toString());
};

const convertToVlanGroup = (response: VlanGroupResponse): VlanGroup => ({
  id: response.id,
  name: response.name,
  siteId: response.site_id || undefined,
  description: response.description || undefined
});

const convertToVlan = (response: VlanResponse): Vlan => ({
  id: response.id,
  vid: response.vid,
  name: response.name || '',
  groupId: response.group_id || undefined,
  siteId: response.site_id || undefined,
  status: response.status,
  description: response.description || ''
});

const loadVlans = async () => {
  try {
    const [groups, vlansData, sitesData, prefixesData] = await Promise.all([
      getVlanGroups(), 
      getVlans(), 
      getSites(), 
      getPrefixes()
    ]);
    vlanGroups.value = groups.map(convertToVlanGroup);
    vlans.value = vlansData.map(convertToVlan);
    sites.value = sitesData;
    prefixes.value = prefixesData;
  } catch (error) {
    console.error('Failed to load VLAN data:', error);
    ElMessage.error(t('vlan.loadFailed'));
  }
};

onMounted(() => {
  loadVlans();
});
</script>

<template>
  <div class="vlan-page">
    <div class="page-header">
      <div class="header-actions">
        <el-button type="primary" @click="openCreateGroupDialog">
          <ElIcon><Plus /></ElIcon>
          {{ t('vlan.addGroup') }}
        </el-button>
        <el-button type="success" @click="openCreateVlanDialog">
          <ElIcon><Plus /></ElIcon>
          {{ t('vlan.addVlan') }}
        </el-button>
      </div>
    </div>

    <div class="vlan-content">
      <div class="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div class="sidebar-header">
          <span v-if="!sidebarCollapsed">{{ t('vlan.vlanGroups') }}</span>
          <el-button 
            class="collapse-btn" 
            icon
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <svg v-if="sidebarCollapsed" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M9 18l6-6-6-6"/>
            </svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M15 18l-6-6 6-6"/>
            </svg>
          </el-button>
        </div>
        <ElTree
          v-show="!sidebarCollapsed"
          :data="groupTreeData"
          :props="{ label: 'label' }"
          default-expand-all
          @node-click="(data) => {
            activeGroupId = data.id === 'all' ? null : Number(data.id);
          }"
        >
          <template #default="{ node, data }">
            <span class="tree-node">
              <span>{{ node.label }}</span>
              <span v-if="data.id !== 'all'" class="tree-actions">
                <el-button 
                  size="small" 
                  icon
                  @click.stop="() => openEditGroupDialog(vlanGroups.find(g => g.id === Number(data.id))!)"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
                  </svg>
                </el-button>
              </span>
            </span>
          </template>
        </ElTree>
        <div class="collapsed-indicator" v-show="sidebarCollapsed">
          <span class="indicator-text">VLAN</span>
        </div>
      </div>

      <div class="main-content">
        <div class="content-header">
          <div class="search-box">
            <el-input
              v-model="searchQuery"
              :placeholder="t('vlan.searchPlaceholder')"
              prefix-icon="Search"
              clearable
              style="width: 280px"
            />
          </div>
          <div class="vid-filter">
            <el-button-group>
              <el-button @click="searchQuery = ''">{{ t('vlan.all') }}</el-button>
              <el-button @click="searchQuery = '1-1024'">1-1024</el-button>
              <el-button @click="searchQuery = '1025-2048'">1025-2048</el-button>
              <el-button @click="searchQuery = '2049-3072'">2049-3072</el-button>
              <el-button @click="searchQuery = '3073-4094'">3073-4094</el-button>
            </el-button-group>
          </div>
        </div>

        <div class="table-container">
          <el-table
            class="vlan-table"
            :data="filteredVlans"
            style="width: 100%; min-width: 900px"
            stripe
            border
            height="calc(100vh - 360px)"
          >
            <el-table-column prop="vid" :label="t('vlan.vlanId')" min-width="100">
              <template #default="{ row }">
                <code class="vid-code">{{ row.vid }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="name" :label="t('vlan.name')" min-width="140">
              <template #default="{ row }">{{ row.name || '-' }}</template>
            </el-table-column>
            <el-table-column prop="groupId" :label="t('vlan.group')" min-width="140">
              <template #default="{ row }">
                {{ vlanGroups.find(g => g.id === row.groupId)?.name || '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="siteId" :label="t('vlan.site')" min-width="140">
              <template #default="{ row }">
                {{ siteName(row.siteId) }}
              </template>
            </el-table-column>
            <el-table-column prop="status" :label="t('vlan.status')" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getStatusTag(row.status).type" effect="light">
                  {{ getStatusTag(row.status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('vlan.prefixCount')" min-width="120">
              <template #default="{ row }">
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click="() => {}"
                >
                  {{ getRelatedPrefixes(row.vid).length }} {{ t('vlan.subnets') }}
                </el-button>
              </template>
            </el-table-column>
            <el-table-column prop="description" :label="t('vlan.description')" />
            <el-table-column :label="t('common.actions')" width="160" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openEditVlanDialog(row)">
                  <ElIcon><Edit /></ElIcon>
                  {{ t('common.edit') }}
                </el-button>
                <el-button link type="danger" size="small" @click="handleDeleteVlan(row)">
                  <ElIcon><Delete /></ElIcon>
                  {{ t('common.delete') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <el-empty
          v-if="filteredVlans.length === 0"
          :description="t('vlan.noData')"
        />
      </div>
    </div>

    <ElDialog
      v-model="showGroupDialog"
      :title="editingGroup ? t('vlan.editGroup') : t('vlan.addGroup')"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item :label="t('vlan.groupName')">
          <el-input v-model="groupForm.name" :placeholder="t('vlan.exampleGroupName')" />
        </el-form-item>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('vlan.site')">
              <el-select v-model="groupForm.siteId" style="width: 100%" :placeholder="t('vlan.global')">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('vlan.status')">
              <el-tag type="success">{{ t('vlan.statusActive') }}</el-tag>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('vlan.description')">
          <el-input v-model="groupForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeGroupDialog">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleSaveGroup">{{ t('common.save') }}</el-button>
      </template>
    </ElDialog>

    <ElDialog
      v-model="showVlanDialog"
      :title="editingVlan ? t('vlan.editVlan') : t('vlan.addVlan')"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('vlan.vlanId')">
              <el-input v-model.number="vlanForm.vid" :placeholder="t('vlan.vidRange')" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('vlan.name')">
              <el-input v-model="vlanForm.name" :placeholder="t('vlan.exampleName')" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('vlan.group')">
              <el-select v-model="vlanForm.groupId" style="width: 100%" :placeholder="t('vlan.none')">
                <el-option v-for="group in vlanGroups" :key="group.id" :label="group.name" :value="group.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="t('vlan.site')">
              <el-select v-model="vlanForm.siteId" style="width: 100%" :placeholder="t('vlan.global')">
                <el-option v-for="site in sites" :key="site.id" :label="site.name" :value="site.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item :label="t('vlan.status')">
              <el-select v-model="vlanForm.status" style="width: 100%">
                <el-option value="active" :label="t('vlan.statusActive')" />
                <el-option value="reserved" :label="t('vlan.statusReserved')" />
                <el-option value="deprecated" :label="t('vlan.statusDeprecated')" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item :label="t('vlan.description')">
          <el-input v-model="vlanForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeVlanDialog">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleSaveVlan">{{ t('common.save') }}</el-button>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.vlan-page {
  padding: 20px;
}

.page-header {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.vlan-content {
  display: flex;
  gap: 20px;
}

.sidebar {
  width: 180px;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
  transition: width 0.3s ease;
  flex-shrink: 0;
  max-height: fit-content;
}

.sidebar.collapsed {
  width: 48px;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f5f5f5;
  font-size: 13px;
  font-weight: 500;
}

.collapse-btn {
  padding: 4px;
  line-height: 1;
  color: #666;
}

.collapsed-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 16px 8px;
}

.indicator-text {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font-size: 12px;
  color: #999;
}

@media (max-width: 900px) {
  .sidebar {
    width: 48px;
  }
  
  .sidebar:not(.collapsed) {
    position: fixed;
    z-index: 100;
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.1);
  }
}

.main-content {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  min-width: 0;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.search-box {
  flex: 1;
  min-width: 200px;
}

.vid-filter {
  margin-left: 0;
}

.table-container {
  overflow-x: auto;
  border-radius: 4px;
}

@media (max-width: 900px) {
  .vlan-page {
    padding: 12px;
  }
  
  .page-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .header-actions {
    flex-wrap: wrap;
  }
  
  .content-header {
    flex-direction: column;
    align-items: stretch;
  }
  
  .vid-filter {
    display: flex;
    overflow-x: auto;
  }
  
  .vid-filter ::deep .el-button-group {
    display: flex;
  }
}

.tree-node {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.tree-actions {
  display: none;
}

.el-tree-node:hover .tree-actions {
  display: flex;
}

.tree-actions .el-button {
  padding: 2px;
  margin-left: 4px;
  color: #666;
}

.tree-actions .el-button:hover {
  color: #1890ff;
}

.vid-code {
  font-family: 'SF Mono', monospace;
  font-size: 14px;
  color: #1890ff;
  background: #e6f7ff;
  padding: 4px 8px;
  border-radius: 4px;
}

.vlan-table :deep(.cell) {
  line-height: 1.5;
}

.vlan-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>