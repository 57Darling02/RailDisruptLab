import { use } from 'echarts/core'
import { BarChart, CustomChart, LineChart, PieChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([
  CustomChart,
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
])
