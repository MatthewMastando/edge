/**
 * Convenience aliases over the generated OpenAPI components. Import domain types from here so
 * call sites do not depend on the generated file's shape.
 */
import type { components } from "./schema";

export type Schemas = components["schemas"];

export type Instrument = Schemas["Instrument"];
export type FuturesContract = Schemas["FuturesContract"];
export type SessionCalendar = Schemas["SessionCalendar"];
export type Bar = Schemas["Bar"];
export type BarSeries = Schemas["BarSeries"];
export type Trade = Schemas["Trade"];
export type MarketSnapshot = Schemas["MarketSnapshot"];
export type TAFeature = Schemas["TAFeature"];
export type TAEvent = Schemas["TAEvent"];
export type Thesis = Schemas["Thesis"];
export type Job = Schemas["Job"];
export type Run = Schemas["Run"];
export type RunEvent = Schemas["RunEvent"];
export type HealthResponse = Schemas["HealthResponse"];
export type AdapterCapabilities = Schemas["AdapterCapabilities"];

export type Provenance = Instrument["provenance"];
export type JobState = Job["state"];
