<script setup>
import { computed, ref } from 'vue'
import BondTable from './components/BondTable.vue'

const items = ref([])
const fetchedAt = ref(null)
const pagesFetched = ref(0)
const dataSource = ref('东方财富数据中心')
const loading = ref(false)
const errorMessage = ref('')

const keyword = ref('')
const onlyListed = ref(false)
const onlyDiscount = ref(false)
const sortKey = ref('')
const sortDirection = ref('none') // 'none' | 'desc' | 'asc'

const listedCount = computed(() => items.value.filter((row) => row.bond_price != null).length)

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

function applyResponse(data) {
  items.value = Array.isArray(data.items) ? data.items : []
  fetchedAt.value = data.fetched_at || null
  pagesFetched.value = data.pages_fetched || 0
  if (data.source) dataSource.value = data.source
}

function clearData() {
  items.value = []
  fetchedAt.value = null
  pagesFetched.value = 0
  errorMessage.value = ''
  resetFilters()
}

async function fetchFromEastmoney() {
  if (loading.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const resp = await fetch('/api/bonds/fetch', { method: 'POST' })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      throw new Error(data.detail || `请求失败（HTTP ${resp.status}）`)
    }
    applyResponse(data)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
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
          <span v-if="fetchedAt">最近获取：{{ fetchedAt }}（{{ pagesFetched }} 页）</span>
          <span v-else>尚未拉取数据（当前版本仅支持手动触发，不自动轮询）</span>
        </div>
      </div>

      <div class="header-actions">
        <button v-if="items.length" class="btn" :disabled="loading" @click="clearData">
          清空数据
        </button>
        <button class="btn btn-primary" :disabled="loading" @click="fetchFromEastmoney">
          {{ loading ? '正在请求东方财富...' : items.length ? '重新获取数据' : '获取数据' }}
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

    <div v-if="errorMessage" class="error-banner">
      {{ errorMessage }}
    </div>

    <main class="table-card">
      <div v-if="!items.length && !loading" class="empty-state">
        <p>当前尚未加载可转债数据，点击下方按钮发起一次全量请求。</p>
        <button class="btn btn-primary" @click="fetchFromEastmoney">获取东方财富可转债数据</button>
      </div>

      <div v-else-if="!filteredAndSortedRows.length && !loading" class="empty-state">
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
