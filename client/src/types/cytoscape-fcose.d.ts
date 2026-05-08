/**
 * Type declaration shim for `cytoscape-fcose` (no official @types pkg).
 * fcose is a force-directed layout extension; we register it via `cytoscape.use(fcose)`.
 */
declare module 'cytoscape-fcose' {
  import type { Ext } from 'cytoscape'
  const fcose: Ext
  export default fcose
}
