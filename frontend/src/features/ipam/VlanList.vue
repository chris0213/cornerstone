<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox, ElTree, ElDialog } from 'element-plus';
import { Plus, Edit, Delete, ArrowDown } from '@element-plus/icons-vue';
import { applyKeywordFilter } from '../../lib/filters';
import { confirmAndRun } from '../../lib/confirm';
import { resolveErrorMessage } from '../../lib/apiError';
import { useCrudForm } from '../../lib/useCrudForm';

const { t } = useI18n();
const router = useRouter();
import type { VlanGroup, Vlan, Prefix } from '../../types/domain';
import type { SiteResponse } from '../../api/sites';
import {
  getVlanGroups, createVlanGroup, updateVlanGroup, deleteVlanGroup,
  getVlans, createVlan, updateVlan, deleteVlan,
  type VlanGroupResponse, type VlanResponse
} from '../../api/vlans';
import { getSites } from '../../api/sites';
import { getPrefixes } from '../../api/ipam';

const sites = ref<SiteResponse[]>([]);
const prefixes = ref<Prefix[]>([]);

function siteName(siteId: number | undefined): string | undefined {
  if (!siteId) return undefined;
  return sites.value.find(s => s.id === siteId)?.name;
}

function groupName(groupId: number | undefined): string | undefined {
  if (!groupId) return undefined;
  return vlanGroups.value.find(g => g.id === groupId)?.name;
}

const vlanGroups = ref<VlanGroup[]>([]);
const vlans = ref<Vlan[]>([]);

const activeGroupId = ref<number | null>(null);
const searchQuery = ref('');
const sidebarCollapsed = ref(false);

// 统计卡片联动筛选：'' | 'active' | 'noSubnet'
const quickFilter = ref<'' | 'active' | 'noSubnet'>('');

// 分页（前端分页）
const currentPage = ref(1);
const pageSize = ref(20);

// 排序（VLAN ID / 子网数量）
const sortProp = ref<'vid' | 'subnetCount' | ''>('');
const sortOrder = ref<'ascending' | 'descending' | null>(null);

// VID 范围快捷筛选（与搜索框联动：选中即写入搜索词，自定义搜索时取消高亮）
const VID_RANGES = ['', '1-1024', '1025-2048', '2049-3072', '3073-4094'] as const;
type VidRange = (typeof VID_RANGES)[number];
const vidRangeOptions: { value: VidRange; i18nKey?: string; label?: string }[] = [
  { value: '', i18nKey: 'vlan.all' },
  { value: '1-1024', label: '1-1024' },
  { value: '1025-2048', label: '1025-2048' },
  { value: '2049-3072', label: '2049-3072' },
  { value: '3073-4094', label: '3073-4094' },
];
const activeVidRange = computed<VidRange | null>(() =>
  (VID_RANGES as readonly string[]).includes(searchQuery.value) ? (searchQuery.value as VidRange) : null
);
const setVidRange = (value: VidRange) => {
  searchQuery.value = value;
  currentPage.value = 1;
};

type GroupForm = { id: number; name: string; siteId: number | undefined; description: string };
type VlanForm = { id: number; vid: number; name: string; groupId: number | undefined; siteId: number | undefined; status: string; description: string };

// 分组弹窗状态
const {
  showDialog: showGroupDialog,
  editing: editingGroup,
  form: groupForm,
  openCreate: openCreateGroupDialog,
  openEdit: openEditGroupDialog,
  closeDialog: closeGroupDialog,
} = useCrudForm<VlanGroup, GroupForm>({
  createDefaults: () => ({ id: 0, name: '', siteId: undefined, description: '' }),
  toForm: (group) => ({
    id: group.id,
    name: group.name,
    siteId: group.siteId,
    description: group.description || ''
  }),
});

// VLAN 弹窗状态
const {
  showDialog: showVlanDialog,
  editing: editingVlan,
  form: vlanForm,
  openCreate: openCreateVlanDialog,
  openEdit: openEditVlanDialog,
  closeDialog: closeVlanDialog,
} = useCrudForm<Vlan, VlanForm>({
  createDefaults: () => ({
    id: 0,
    vid: 0,
    name: '',
    groupId: activeGroupId.value || undefined,
    siteId: undefined,
    status: 'active',
    description: ''
  }),
  toForm: (vlan) => ({
    id: vlan.id,
    vid: vlan.vid,
    name: vlan.name || '',
    groupId: vlan.groupId || undefined,
    siteId: vlan.siteId || undefined,
    status: vlan.status,
    description: vlan.description || ''
  }),
});

const filteredVlans = computed(() => {
  let result = vlans.value;
  if (activeGroupId.value !== null) {
    result = result.filter(v => v.groupId === activeGroupId.value);
  }
  if (quickFilter.value === 'active') {
    result = result.filter(v => v.status === 'active');
  } else if (quickFilter.value === 'noSubnet') {
    result = result.filter(v => getRelatedPrefixes(v).length === 0);
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
  // 排序（VLAN ID / 子网数量）
  if (sortProp.value && sortOrder.value) {
    const dir = sortOrder.value === 'ascending' ? 1 : -1;
    if (sortProp.value === 'vid') {
      result = [...result].sort((a, b) => (a.vid - b.vid) * dir);
    } else {
      result = [...result].sort((a, b) => (getRelatedPrefixes(a).length - getRelatedPrefixes(b).length) * dir);
    }
  }
  return result;
});

const pagedVlans = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredVlans.value.slice(start, start + pageSize.value);
});

// 统计卡片数字
const totalCount = computed(() => vlans.value.length);
const activeCount = computed(() => vlans.value.filter(v => v.status === 'active').length);
const noSubnetCount = computed(() => vlans.value.filter(v => getRelatedPrefixes(v).length === 0).length);

const toggleQuickFilter = (key: 'active' | 'noSubnet') => {
  quickFilter.value = quickFilter.value === key ? '' : key;
  currentPage.value = 1;
};

const quickFilterLabel = computed(() => {
  if (quickFilter.value === 'active') return t('vlan.statActive');
  if (quickFilter.value === 'noSubnet') return t('vlan.statNoSubnet');
  return '';
});

const groupTreeData = computed(() => {
  const groups = vlanGroups.value.map(group => ({
    id: group.id.toString(),
    label: group.name,
    count: vlans.value.filter(v => v.groupId === group.id).length,
    children: []
  }));
  return [
    {
      id: 'all',
      label: t('vlan.allVlans'),
      count: vlans.value.length,
      children: groups
    }
  ];
});

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
    ElMessage.error(resolveErrorMessage(error, 'vlan.saveFailed'));
  }
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
  } catch (error) {
    console.error('Failed to save VLAN:', error);
    ElMessage.error(resolveErrorMessage(error, 'vlan.vlanSaveFailed'));
  }
};

const getStatusTag = (status: string) => {
  const tags: Record<string, { type: string; text: string }> = {
    active: { type: 'success', text: t('vlan.statusActive') },
    reserved: { type: 'warning', text: t('vlan.statusReserved') },
    deprecated: { type: 'danger', text: t('vlan.statusDeprecated') }
  };
  return tags[status] || { type: 'info', text: status };
};

// 关联子网口径：同 VID 且同站点（与后端 /vlans/{id}/prefixes 一致，避免跨站点误关联）
const getRelatedPrefixes = (vlan: Vlan) => {
  return prefixes.value.filter(p => {
    if (p.vlan !== vlan.vid.toString()) return false;
    return vlan.siteId ? p.siteId === vlan.siteId : !p.siteId;
  });
};

// 子网数量列点击：跳转 IP 管理并带站点 + VLAN 过滤
const goIpamWithFilter = (vlan: Vlan) => {
  router.push({
    path: '/ipam',
    query: {
      siteId: vlan.siteId ? String(vlan.siteId) : 'none',
      vlan: String(vlan.vid)
    }
  });
};

const handleSortChange = ({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) => {
  sortProp.value = (prop === 'vid' || prop === 'subnetCount') ? prop : '';
  sortOrder.value = order;
  currentPage.value = 1;
};

const handleDeleteVlan = async (vlan: Vlan) => {
  // 与后端同口径统计关联子网数：有关联时删除会被后端 400 拒绝，直接提示不进确认
  // （菜单项已置灰，此弹窗为兜底：数据未刷新时的竞态场景）
  const relatedCount = getRelatedPrefixes(vlan).length;
  if (relatedCount > 0) {
    ElMessageBox.alert(
      t('vlan.deleteBlockedSubnets', { vid: vlan.vid, count: relatedCount }),
      t('vlan.cannotDelete'),
      { type: 'warning', confirmButtonText: t('common.ok') }
    );
    return;
  }

  await confirmAndRun({
    message: t('vlan.confirmDeleteVlan', { vid: vlan.vid }),
    title: t('common.confirmDelete'),
    confirmText: t('common.confirmDelete'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteVlan(vlan.id);
      vlans.value = vlans.value.filter(v => v.id !== vlan.id);
    },
    successMessage: t('vlan.vlanDeleteSuccess'),
    errorMessage: (error) => resolveErrorMessage(error, 'vlan.vlanDeleteFailed'),
  });
};

const handleDeleteGroup = async (group: VlanGroup) => {
  // 与后端同口径：组下有 VLAN 时删除会被 400 拒绝，直接提示
  const vlanCount = vlans.value.filter(v => v.groupId === group.id).length;
  if (vlanCount > 0) {
    ElMessageBox.alert(
      t('vlan.groupDeleteBlocked', { name: group.name, count: vlanCount }),
      t('common.warning'),
      { type: 'warning', confirmButtonText: t('common.ok') }
    );
    return;
  }

  await confirmAndRun({
    message: t('vlan.confirmDeleteGroup', { name: group.name }),
    title: t('common.confirmDelete'),
    confirmText: t('common.confirmDelete'),
    cancelText: t('common.cancel'),
    danger: true,
    action: async () => {
      await deleteVlanGroup(group.id);
      vlanGroups.value = vlanGroups.value.filter(g => g.id !== group.id);
      if (activeGroupId.value === group.id) {
        activeGroupId.value = null;
      }
    },
    successMessage: t('vlan.groupDeleteSuccess'),
    errorMessage: (error) => resolveErrorMessage(error, 'vlan.groupDeleteFailed'),
  });
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
    <div class="overview-cards">
      <div class="overview-card overview-card-blue">
        <div class="overview-card-label">{{ t('vlan.statTotal') }}</div>
        <div class="overview-card-value">{{ totalCount }}</div>
        <div class="overview-card-trend">{{ t('vlan.statTotalTrend') }}</div>
      </div>
      <div
        class="overview-card overview-card-success"
        :class="{ 'overview-card-clickable': activeCount > 0, 'is-active': quickFilter === 'active' }"
        @click="activeCount > 0 && toggleQuickFilter('active')"
      >
        <div class="overview-card-label">{{ t('vlan.statActive') }}</div>
        <div class="overview-card-value">{{ activeCount }}</div>
        <div class="overview-card-trend">{{ t('vlan.statActiveTrend') }}</div>
      </div>
      <div
        class="overview-card overview-card-warning"
        :class="{ 'overview-card-clickable': noSubnetCount > 0, 'is-active': quickFilter === 'noSubnet' }"
        @click="noSubnetCount > 0 && toggleQuickFilter('noSubnet')"
      >
        <div class="overview-card-label">{{ t('vlan.statNoSubnet') }}</div>
        <div class="overview-card-value">{{ noSubnetCount }}</div>
        <div class="overview-card-trend">{{ t('vlan.statNoSubnetTrend') }}</div>
      </div>
    </div>

    <div v-if="quickFilter" class="quick-filter-bar">
      <el-tag closable @close="toggleQuickFilter(quickFilter)">
        {{ t('vlan.filterBarLabel', { label: quickFilterLabel }) }}
      </el-tag>
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
              <el-tooltip :content="node.label" :disabled="!node.label" placement="top" :show-after="300">
                <span class="tree-label">{{ node.label }}</span>
              </el-tooltip>
              <span class="tree-right">
                <span class="tree-count">{{ data.count }}</span>
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
                  <el-button
                    size="small"
                    icon
                    class="tree-delete-btn"
                    @click.stop="() => handleDeleteGroup(vlanGroups.find(g => g.id === Number(data.id))!)"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>
                    </svg>
                  </el-button>
                </span>
              </span>
            </span>
          </template>
        </ElTree>
        <div class="collapsed-indicator" v-show="sidebarCollapsed">
          <span class="indicator-text">VLAN</span>
        </div>
      </div>

      <div class="main-content">
        <!-- 工具行：搜索框 + VID 范围快捷筛选 + 新增按钮，同一行 -->
        <div class="toolbar-row">
          <div class="search-box">
            <el-input
              v-model="searchQuery"
              :placeholder="t('vlan.searchPlaceholder')"
              prefix-icon="Search"
              clearable
              style="width: 240px"
            />
          </div>
          <div class="vid-filter">
            <el-button-group>
              <el-button
                v-for="opt in vidRangeOptions"
                :key="opt.value || 'all'"
                :class="{ 'is-current': activeVidRange === opt.value }"
                @click="setVidRange(opt.value)"
              >
                {{ opt.i18nKey ? t(opt.i18nKey) : opt.label }}
              </el-button>
            </el-button-group>
          </div>
          <el-dropdown split-button type="primary" class="create-dropdown" @click="openCreateVlanDialog" @command="(cmd: string) => cmd === 'group' && openCreateGroupDialog()">
            {{ t('vlan.addVlan') }}
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="group">
                  <el-icon><Plus /></el-icon>
                  {{ t('vlan.addGroup') }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div class="table-container">
          <el-table
            class="vlan-table"
            :data="pagedVlans"
            style="width: 100%; min-width: 900px"
            border
            height="calc(100vh - 440px)"
            @sort-change="handleSortChange"
          >
            <el-table-column prop="vid" :label="t('vlan.vlanId')" width="150" sortable="custom">
              <template #default="{ row }">
                <code class="vid-code">{{ row.vid }}</code>
              </template>
            </el-table-column>
            <el-table-column prop="name" :label="t('vlan.name')" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">{{ row.name || '-' }}</template>
            </el-table-column>
            <el-table-column prop="groupId" :label="t('vlan.group')" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="groupName(row.groupId)">{{ groupName(row.groupId) }}</span>
                <span v-else class="empty-placeholder">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="siteId" :label="t('vlan.site')" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="siteName(row.siteId)">{{ siteName(row.siteId) }}</span>
                <span v-else class="empty-placeholder">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="status" :label="t('vlan.status')" width="90">
              <template #default="{ row }">
                <el-tag :type="getStatusTag(row.status).type" effect="light">
                  {{ getStatusTag(row.status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="subnetCount" :label="t('vlan.prefixCount')" width="150" sortable="custom" align="center">
              <template #default="{ row }">
                <el-button
                  v-if="getRelatedPrefixes(row).length > 0"
                  link
                  type="primary"
                  size="small"
                  class="nowrap"
                  :title="t('vlan.viewSubnetsTitle')"
                  @click="goIpamWithFilter(row)"
                >
                  {{ t('vlan.subnetCountValue', { count: getRelatedPrefixes(row).length }) }}
                </el-button>
                <span v-else class="subnet-zero">{{ t('vlan.subnetCountValue', { count: 0 }) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="description" :label="t('vlan.description')" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.description || '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" width="120" fixed="right" align="center">
              <template #default="{ row }">
                <div class="actions-cell">
                  <el-button link type="primary" size="small" @click="openEditVlanDialog(row)">
                    <ElIcon><Edit /></ElIcon>
                    {{ t('common.edit') }}
                  </el-button>
                  <el-dropdown trigger="click">
                    <el-button link type="primary" size="small">
                      {{ t('common.more') }}
                      <el-icon><ArrowDown /></el-icon>
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <!-- 被子网引用时禁用删除；disabled 元素收不到鼠标事件，tooltip 挂在菜单项内层的 span 上 -->
                        <el-tooltip
                          :content="t('vlan.deleteBlockedSubnets', { vid: row.vid, count: getRelatedPrefixes(row).length })"
                          :disabled="getRelatedPrefixes(row).length === 0"
                          placement="left"
                          :show-after="200"
                        >
                          <el-dropdown-item
                            class="danger-item"
                            :disabled="getRelatedPrefixes(row).length > 0"
                            @click="handleDeleteVlan(row)"
                          >
                            <span class="danger-entry" :title="getRelatedPrefixes(row).length > 0 ? t('vlan.deleteBlockedSubnets', { vid: row.vid, count: getRelatedPrefixes(row).length }) : undefined">
                              <el-icon class="danger-icon"><Delete /></el-icon>
                              <span class="danger-text">{{ t('common.delete') }}</span>
                            </span>
                          </el-dropdown-item>
                        </el-tooltip>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="table-pagination">
          <el-pagination
            v-model:current-page="currentPage"
            v-model:page-size="pageSize"
            :total="filteredVlans.length"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            background
          />
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

/* 统计卡片：首卡与左侧组树栏（180px）对齐，其余与主内容区对齐，间距 20px 同 vlan-content */
.overview-cards {
  display: grid;
  grid-template-columns: 180px 1fr 1fr;
  gap: 20px;
  margin-bottom: 16px;
}

.overview-card {
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 20px;
  border-left: 3px solid var(--el-text-color-secondary);
  transition: all 0.2s ease;
}

.overview-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--el-box-shadow-light);
}

.overview-card-success { border-left-color: var(--el-color-success); }
.overview-card-warning { border-left-color: var(--el-color-warning); }
.overview-card-blue { border-left-color: var(--el-color-primary); }

.overview-card-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.overview-card-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  line-height: 1.2;
  margin-bottom: 4px;
}

.overview-card-trend {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.overview-card-clickable {
  cursor: pointer;
}

.overview-card-clickable:hover {
  border-color: var(--el-color-primary-light-5);
}

.overview-card.is-active {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

/* 卡片联动筛选提示条 */
.quick-filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}

.quick-filter-bar .el-tag {
  font-size: 13px;
}

.vlan-content {
  display: flex;
  gap: 20px;
}

.sidebar {
  width: 180px;
  background: var(--el-bg-color);
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
  background: var(--el-fill-color-light);
  font-size: 13px;
  font-weight: 500;
}

.collapse-btn {
  padding: 4px;
  line-height: 1;
  color: var(--el-text-color-regular);
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
  color: var(--el-text-color-placeholder);
}

.main-content {
  flex: 1;
  background: var(--el-bg-color);
  border-radius: 8px;
  padding: 16px;
  min-width: 0;
}

/* 工具行：搜索框 + VID 范围 + 新增按钮同行 */
.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.search-box {
  min-width: 200px;
}

.create-dropdown {
  white-space: nowrap;
}

.vid-filter {
  flex-shrink: 0;
}

/* VID 范围快捷筛选选中态：明显高亮 */
.vid-filter .el-button.is-current {
  --el-button-bg-color: var(--el-color-primary);
  --el-button-border-color: var(--el-color-primary);
  --el-button-text-color: #fff;
  --el-button-hover-bg-color: var(--el-color-primary-light-3);
  --el-button-hover-border-color: var(--el-color-primary-light-3);
  --el-button-hover-text-color: #fff;
  --el-button-active-bg-color: var(--el-color-primary-dark-2);
  --el-button-active-border-color: var(--el-color-primary-dark-2);
  --el-button-active-text-color: #fff;
}

/* VLAN ID 表头不换行 */
.vlan-table :deep(th.el-table__cell .cell) {
  white-space: nowrap;
}

.table-container {
  overflow-x: auto;
  border-radius: 4px;
}

/* 操作列：编辑靠左、「更多」靠右，位置一致 */
.actions-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  white-space: nowrap;
}

/* 「更多」菜单中的红色删除项（菜单挂 body，需全局选择器） */
.vlan-table :deep(.danger-item) {
  color: var(--el-color-danger);
}

.table-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 900px) {
  .vlan-page {
    padding: 12px;
  }

  .overview-card {
    padding: 12px;
  }

  .overview-card-value {
    font-size: 20px;
  }

  .toolbar-row {
    flex-direction: column;
    align-items: stretch;
  }

  .vid-filter {
    display: flex;
    overflow-x: auto;
  }

  .vid-filter :deep(.el-button-group) {
    display: flex;
  }
}

.tree-node {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  min-width: 0;
}

.tree-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.tree-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 0 6px;
  line-height: 16px;
}

.tree-actions {
  display: none;
}

.el-tree-node:hover .tree-actions {
  display: flex;
}

.tree-actions .el-button {
  padding: 2px;
  margin-left: 0;
  color: var(--el-text-color-regular);
}

.tree-actions .el-button:hover {
  color: var(--el-color-primary);
}

.tree-actions .tree-delete-btn:hover {
  color: var(--el-color-danger);
}

/* 子网数量为零：纯文本无链接色 */
.subnet-zero {
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

/* 空值占位：灰色 em dash（与全局一致） */
.empty-placeholder {
  color: var(--el-text-color-placeholder);
}

/* 组树节点标签：溢出省略（tooltip 已加） */
.tree-label {
  min-width: 0;
}

.nowrap {
  white-space: nowrap;
}

.vid-code {
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 14px;
  color: var(--el-text-color-primary);
  background: transparent;
  padding: 0;
  border-radius: 0;
}

.vlan-table :deep(.cell) {
  line-height: 1.5;
}

.vlan-table :deep(.el-table__cell) {
  padding: 8px 12px;
}
</style>