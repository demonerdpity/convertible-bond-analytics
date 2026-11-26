<script setup>
import { ref } from 'vue'

const props = defineProps({
  rows: {
    type: Array,
    required: true,
  },
  sortKey: {
    type: String,
    default: '',
  },
  sortDirection: {
    type: String,
    default: 'none', // 'none' | 'desc' | 'asc'
  },
})

const emit = defineEmits(['toggle-sort'])

const PURE_BOND_TOOLTIP = '按剩余票息和到期赎回价，结合信用评级参考收益率本地贴现估算。'
const CONVERSION_TOOLTIP =
  '每投入100元按当前转债价格买入后立即转股，对应的股票市值：100 ÷ 转债现价 ×（100 ÷ 转股价 × 正股价）。'

const columns = [
  { key: 'bond_code', label: '债券代码', align: 'left', sticky: 'sticky-col-2', sortable: true },
  { key: 'bond_name', label: '债券简称', align: 'left', sticky: 'sticky-col-3', sortable: false },
  { key: 'bond_price', label: '转债最新价', digits: 3, sortable: true },
  { key: 'bond_change_pct', label: '转债涨跌幅', digits: 2, suffix: '%', signedColor: true, sortable: true },
  { key: 'stock_code', label: '正股代码', align: 'left', sortable: true },
  { key: 'stock_name', label: '正股简称', align: 'left', sortable: false },
  { key: 'stock_price', label: '正股最新价', digits: 2, sortable: true },
  { key: 'stock_change_pct', label: '正股涨跌幅', digits: 2, suffix: '%', signedColor: true, sortable: true },
  { key: 'conversion_price', label: '转股价', digits: 2, sortable: true },
  { key: 'conversion_value', label: '转股价值', digits: 4, sortable: true },
  { key: 'conversion_premium_pct', label: '转股溢价率', digits: 2, suffix: '%', sortable: true },
  { key: 'pure_bond_premium_pct', label: '纯债溢价率', digits: 2, suffix: '%', sortable: true },
  { key: 'put_trigger_price', label: '回售触发价', digits: 2, sortable: true },
  { key: 'call_trigger_price', label: '强赎触发价', digits: 2, sortable: true },
  { key: 'maturity_redemption_price', label: '到期赎回价', digits: 2, sortable: true },
  { key: 'pure_bond_value', label: '纯债价值', digits: 4, sortable: true, tooltip: PURE_BOND_TOOLTIP },
  {
    key: 'conversion_market_value_per_100',
    label: '每百元现价转股市值',
    digits: 4,
    sortable: true,
    highlight: true,
    tooltip: CONVERSION_TOOLTIP,
  },
  { key: 'conversion_start_date', label: '开始转股日', align: 'center', sortable: true },
  { key: 'listing_date', label: '上市日期', align: 'center', sortable: true },
  { key: 'subscription_date', label: '申购日期', align: 'center', sortable: true },
]

const tooltipState = ref({
  visible: false,
  text: '',
  left: 0,
  top: 0,
})

function showTooltip(event, text) {
  const rect = event.currentTarget.getBoundingClientRect()
  const maxWidth = 320
  const left = Math.min(Math.max(8, rect.left), window.innerWidth - maxWidth - 12)
  const top = rect.bottom + 8
  tooltipState.value = {
    visible: true,
    text,
    left,
    top,
  }
}

function hideTooltip() {
  tooltipState.value.visible = false
}

function handleHeaderClick(col) {
  if (!col.sortable) return
  emit('toggle-sort', col.key)
}

function formatCell(row, col) {
  const val = row[col.key]
  if (val === null || val === undefined || val === '') return '--'
  if (typeof val === 'number') {
    const fixed = col.digits != null ? val.toFixed(col.digits) : String(val)
    return col.suffix ? `${fixed}${col.suffix}` : fixed
  }
  return String(val)
}

function valueClass(row, col) {
  const classes = []
  if (col.align === 'left') classes.push('align-left')
  if (col.align === 'center') classes.push('align-center')
  if (col.sticky) classes.push(col.sticky)

  const val = row[col.key]
  if (val === null || val === undefined || val === '') {
    classes.push('val-muted')
    return classes
  }

  if (col.key === 'conversion_market_value_per_100') {
    classes.push(val >= 100 ? 'col-discount' : 'col-highlight')
    return classes
  }

  if (col.signedColor && typeof val === 'number') {
    if (val > 0) classes.push('val-up')
    else if (val < 0) classes.push('val-down')
  }
  return classes
}

function bondUrl(row) {
  const prefix = row.bond_market === 1 ? 'sh' : 'sz'
  return `https://quote.eastmoney.com/bond/${prefix}${row.bond_code}.html`
}

function stockUrl(row) {
  if (!row.stock_code) return ''
  const prefix = row.stock_market === 1 ? 'sh' : 'sz'
  return `https://quote.eastmoney.com/${prefix}${row.stock_code}.html`
}
</script>

<template>
  <div class="table-scroll">
    <table class="cb-table">
      <thead>
        <tr>
          <th class="align-center sticky-col-1">序号</th>
          <th
            v-for="col in columns"
            :key="col.key"
            :class="[
              col.align === 'left' ? 'align-left' : col.align === 'center' ? 'align-center' : '',
              col.sticky || '',
              col.sortable ? 'sortable' : '',
              col.highlight ? 'col-highlight' : '',
            ]"
            @click="handleHeaderClick(col)"
          >
            <span>{{ col.label }}</span>
            <span
              v-if="col.tooltip"
              class="help-icon"
              @mouseenter="showTooltip($event, col.tooltip)"
              @mouseleave="hideTooltip"
              @click.stop
            >
              ⓘ
            </span>
            <span
              v-if="col.sortable"
              class="sort-arrow"
              :class="{ inactive: sortKey !== col.key || sortDirection === 'none' }"
            >
              <template v-if="sortKey === col.key && sortDirection === 'asc'">↑</template>
              <template v-else-if="sortKey === col.key && sortDirection === 'desc'">↓</template>
              <template v-else>⇅</template>
            </span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row.bond_code">
          <td class="align-center sticky-col-1 val-muted">{{ index + 1 }}</td>
          <td v-for="col in columns" :key="col.key" :class="valueClass(row, col)">
            <a
              v-if="col.key === 'bond_name'"
              :href="bondUrl(row)"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ row.bond_name }}
            </a>
            <a
              v-else-if="col.key === 'stock_name' && row.stock_code"
              :href="stockUrl(row)"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ row.stock_name || '--' }}
            </a>
            <template v-else>
              {{ formatCell(row, col) }}
            </template>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div
    v-if="tooltipState.visible"
    class="floating-tooltip"
    :style="{ left: `${tooltipState.left}px`, top: `${tooltipState.top}px` }"
  >
    {{ tooltipState.text }}
  </div>
</template>
