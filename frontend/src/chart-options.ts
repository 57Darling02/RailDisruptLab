export function chartDownloadToolbox(name = 'rail-disrupt-chart') {
  return {
    right: 8,
    top: 0,
    feature: {
      saveAsImage: {
        type: 'png',
        title: '下载 PNG',
        name,
        pixelRatio: 2,
        backgroundColor: '#fff',
      },
    },
  }
}
