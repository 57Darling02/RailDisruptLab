export function barValueLabel() {
  return {
    show: true,
    position: 'top',
    fontSize: 10,
    color: '#606266',
    formatter: ({ value }: { value: unknown }) => formatBarLabelValue(value),
  }
}

export function barPercentLabel() {
  return {
    ...barValueLabel(),
    formatter: ({ value }: { value: unknown }) => {
      const number = numberFromChartValue(value)
      return number == null ? '' : `${(number * 100).toFixed(1)}%`
    },
  }
}

function formatBarLabelValue(value: unknown) {
  const number = numberFromChartValue(value)
  if (number == null) return ''
  if (Math.abs(number) >= 1000) return number.toFixed(0)
  if (Math.abs(number) >= 10) return number.toFixed(1)
  if (Number.isInteger(number)) return String(number)
  return number.toFixed(2)
}

function numberFromChartValue(value: unknown) {
  const raw = Array.isArray(value) ? value.at(-1) : value
  const number = Number(raw)
  return Number.isFinite(number) ? number : null
}
