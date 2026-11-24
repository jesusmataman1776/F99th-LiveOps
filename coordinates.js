/* WGS84 cursor formats. MGRS conversion: vendored proj4js/mgrs 2.2.0. */
function cursorFormats(lat, lon) {
  const angle = (value, latitude, seconds) => {
    const scale = seconds ? 36000 : 60000;
    const total = Math.round(Math.abs(value) * scale);
    const degrees = Math.floor(total / scale);
    const remainder = total % scale;
    const hemisphere = latitude ? (value < 0 ? 'S' : 'N') : (value < 0 ? 'W' : 'E');
    const prefix = `${hemisphere} ${String(degrees).padStart(latitude ? 2 : 3, '0')}°`;
    return seconds
      ? `${prefix}${String(Math.floor(remainder / 600)).padStart(2, '0')}′${(remainder % 600 / 10).toFixed(1).padStart(4, '0')}″`
      : `${prefix}${(remainder / 1000).toFixed(3).padStart(6, '0')}′`;
  };
  let grid = 'Unavailable outside 80°S–84°N';
  if (lat >= -80 && lat <= 84) {
    try { grid = mgrs.forward([lon, lat], 5).replace(/^(\d{1,2}[A-Z])([A-Z]{2})(\d{5})(\d{5})$/, '$1 $2 $3 $4'); }
    catch { grid = 'Unavailable'; }
  }
  return {ddm: `${angle(lat, true, false)} / ${angle(lon, false, false)}`,
    dms: `${angle(lat, true, true)} / ${angle(lon, false, true)}`, mgrs: grid};
}
