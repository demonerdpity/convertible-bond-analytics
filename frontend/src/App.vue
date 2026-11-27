<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import BondTable from './components/BondTable.vue'

const FRONTEND_POLL_MS = 20_000

const items = ref([])
const fetchedAt = ref(null)
const baseFetchedAt = ref(null)
const dataSource = ref('东方财富数据中心')
const isTradingTime = ref(false)
const quoteRefreshSeconds = ref(45)
const baseRefreshSeconds = ref(900)

const initialLoading = ref(false)
const manualRefreshing = ref(false)
const noticeMessage = ref('')
const noticeType = ref('info') // 'info' | 'error'

const keyword = ref('')
const onlyListed = ref(false)
const onlyDiscount = ref(false)
const sortKey = ref('')
const sortDirection = ref('none') // 'none' | 'desc' | 'asc'

let pollTimer = null

const listedCount = computed(() => items.value.filter((row) => row.bond_price != null).length)

const refreshPolicyText = computed(() => {
  const baseMin = Math.round(baseRefreshSeconds.value / 60)
  if (isTradingTime.value) {
    return `盘中自动刷新（报价 ${quoteRefreshSeconds.value}s / 条款 ${baseMin}m）`
  }
  return '非交易时段（已暂停上游请求，读取最新收盘快照）'
})

const filteredAndSortedRows = computed(() => {
  const kw = keyword.value.trim().toLowerCase()

  let list = items.value.filter((row) => {
    if (onlyListed.value && row.bond_price == null) return false
    if (onlyDiscount.value) {
      const val = row.conversion_market_value_per_100
      if (val == null || val < 100) return false
    }
    if (kw) {
      const haystack = [row.bond_code, row.bond_name, row.stock_code, row.stock_name]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(kw)) return false
    }
    return true
  })

  if (sortKey.value && sortDirection.value !== 'none') {
    const key = sortKey.value
    const dir = sortDirection.value
    list = [...list].sort((a, b) => {
      const left = a[key]
      const right = b[key]
      const leftEmpty = left === null || left === undefined || left === ''
      const rightEmpty = right === null || right === undefined || right === ''
      if (leftEmpty && rightEmpty) return 0
      if (leftEmpty) return 1
      if (rightEmpty) return -1

      if (typeof left === 'number' && typeof right === 'number') {
        return dir === 'asc' ? left - right : right - left
      }
      const cmp = String(left).localeCompare(String(right), 'zh-CN')
      return dir === 'asc' ? cmp : -cmp
    })
  }

  return list
})

function applyResponseIfValid(data) {
  if (!data || !Array.isArray(data.items) || data.items.length === 0) {
    return false
  }
  items.value = data.items
  fetchedAt.value = data.fetched_at || null
  baseFetchedAt.value = data.base_fetched_at || data.fetched_at || null
  if (data.source) dataSource.value = data.source
  isTradingTime.value = Boolean(data.is_trading_time)
  if (data.quote_refresh_seconds) quoteRefreshSeconds.value = data.quote_refresh_seconds
  if (data.base_refresh_seconds) baseRefreshSeconds.value = data.base_refresh_seconds
  return true
}

function showNotice(message, type = 'info') {
  noticeMessage.value = message
  noticeType.value = type
}

function dismissNotice() {
  noticeMessage.value = ''
}

async function loadSnapshot({ silent = false } = {}) {
  if (!silent && items.value.length === 0) {
    initialLoading.value = true
  }
  try {
    const resp = await fetch('/api/bonds')
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      throw new Error(data.detail || `读取数据失败（HTTP ${resp.status}）`)
    }
    const updated = applyResponseIfValid(data)
    if (updated && !silent) {
      noticeMessage.value = ''
    }
  } catch (err) {
    // 静默轮询失败或已有旧数据时，不清空表格
    if (!silent) {
      const msg = err instanceof Error ? err.message : String(err)
      showNotice(
        items.value.length ? `读取最新快照失败，已保留旧数据：${msg}` : `加载数据失败：${msg}`,
        'error'
      )
    }
  } finally {
    initialLoading.value = false
  }
}

async function manualFetch() {
  if (manualRefreshing.value) return
  manualRefreshing.value = true
  try {
    const resp = await fetch('/api/bonds/fetch', { method: 'POST' })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`)
    }
    // 只有成功拿到有效非空数据，才替换旧数据
    const replaced = applyResponseIfValid(data)
    if (!replaced) {
      throw new Error('接口返回空列表，已保留当前页面数据')
    }
    if (data.from_cache) {
      showNotice('距离上次拉取不足 20 秒，已复用最新快照。', 'info')
    } else {
      noticeMessage.value = ''
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    showNotice(
      items.value.length ? `手动刷新失败，已保留旧数据：${msg}` : `获取数据失败：${msg}`,
      'error'
    )
  } finally {
    manualRefreshing.value = false
  }
}

function toggleSort(key) {
  if (sortKey.value !== key) {
    sortKey.value = key
    sortDirection.value = 'desc'
    return
  }
  if (sortDirection.value === 'desc') {
    sortDirection.value = 'asc'
  } else if (sortDirection.value === 'asc') {
    sortDirection.value = 'none'
    sortKey.value = ''
  } else {
    sortDirection.value = 'desc'
  }
}

function setQuickSort(key, direction) {
  if (sortKey.value === key && sortDirection.value === direction) {
    sortKey.value = ''
    sortDirection.value = 'none'
  } else {
    sortKey.value = key
    sortDirection.value = direction
  }
}

function resetFilters() {
  keyword.value = ''
  onlyListed.value = false
  onlyDiscount.value = false
  sortKey.value = ''
  sortDirection.value = 'none'
}

onMounted(() => {
  loadSnapshot({ silent: false })
  pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !manualRefreshing.value) {
      loadSnapshot({ silent: true })
    }
  }, FRONTEND_POLL_MS)
})

onBeforeUnmount(() => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="app-shell">
    <header class="top-header">
      <div class="title-group">
        <h1>可转债比价看板</h1>
        <div class="title-meta">
          <span>数据源：{{ dataSource }}</span>
          <span v-if="items.length">
            共 {{ items.length }} 只（已上市 {{ listedCount }} 只，当前显示 {{ filteredAndSortedRows.length }} 只）
          </span>
          <span v-if="fetchedAt">行情更新：{{ fetchedAt }}</span>
          <span v-if="baseFetchedAt && baseFetchedAt !== fetchedAt">条款更新：{{ baseFetchedAt }}</span>
          <span class="status-pill" :class="{ live: isTradingTime }">
            {{ refreshPolicyText }}
          </span>
        </div>
      </div>

      <div class="header-actions">
        <button class="btn btn-primary" :disabled="manualRefreshing" @click="manualFetch">
          {{ manualRefreshing ? '刷新中（保留旧数据）...' : '手动刷新' }}
        </button>
      </div>
    </header>

    <section class="toolbar">
      <div class="filter-left">
        <input
          v-model="keyword"
          class="search-input"
          type="text"
          placeholder="搜索债券代码 / 简称 / 正股..."
        />
        <label class="checkbox-label">
          <input v-model="onlyListed" type="checkbox" />
          仅看已上市
        </label>
        <label class="checkbox-label">
          <input v-model="onlyDiscount" type="checkbox" />
          仅看每百元转股市值 ≥ 100
        </label>
      </div>

      <div class="quick-sorts">
        <button
          class="chip"
          :class="{ active: sortKey === 'conversion_market_value_per_100' && sortDirection === 'desc' }"
          @click="setQuickSort('conversion_market_value_per_100', 'desc')"
        >
          每百元转股市值 ↓
        </button>
        <button
          class="chip"
          :class="{ active: sortKey === 'pure_bond_value' && sortDirection === 'desc' }"
          @click="setQuickSort('pure_bond_value', 'desc')"
        >
          纯债价值 ↓
        </button>
        <button
          class="chip"
          :class="{ active: sortKey === 'conversion_premium_pct' && sortDirection === 'asc' }"
          @click="setQuickSort('conversion_premium_pct', 'asc')"
        >
          转股溢价率 ↑
        </button>
        <button class="chip" @click="resetFilters">重置</button>
      </div>
    </section>

    <div v-if="noticeMessage" class="notice-banner" :class="noticeType">
      <span>{{ noticeMessage }}</span>
      <button class="notice-close" type="button" aria-label="关闭提示" @click="dismissNotice">×</button>
    </div>

    <main class="table-card">
      <div v-if="initialLoading && !items.length" class="empty-state">
        <p>正在自动加载可转债数据，请稍候...</p>
      </div>

      <div v-else-if="!items.length" class="empty-state">
        <p>暂未获取到可转债数据，请点击下方按钮重试。</p>
        <button class="btn btn-primary" :disabled="manualRefreshing" @click="manualFetch">
          {{ manualRefreshing ? '正在获取...' : '重试获取数据' }}
        </button>
      </div>

      <div v-else-if="!filteredAndSortedRows.length" class="empty-state">
        <p>没有符合当前筛选条件的可转债。</p>
        <button class="btn" @click="resetFilters">清空筛选条件</button>
      </div>

      <BondTable
        v-else
        :rows="filteredAndSortedRows"
        :sort-key="sortKey"
        :sort-direction="sortDirection"
        @toggle-sort="toggleSort"
      />
    </main>
  </div>
</template>
