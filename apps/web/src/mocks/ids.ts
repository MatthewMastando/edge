/** uuid5 ids from the fixture generator namespace, so mocks match `trading_core.fixtures`. */
export const IDS = {
  instrument6E: "edd6f053-f27c-564d-a895-01e646752c32",
  instrumentGC: "6acbb3f3-35c1-51e8-b38e-eae3c5993904",
  instrumentCL: "496a1f76-dc59-56bb-a0bd-ac481ae08593",
  instrumentES: "2b0c2d97-32fd-54e1-9acc-b766eb879be3",
  instrumentSPY: "47a2f827-2084-5938-b373-29662da1aaf8",
  instrumentBTC: "b4664dca-7f0e-53e4-87a9-0f875cf14a5e",
  contract6EZ6: "ecd5eb76-c5ea-5d97-b6c6-3c48f9e81ed1",
  contractGCZ6: "3614dae1-0db5-5de0-a5fd-0484316a0c45",
  contractCLX6: "ce57b40a-b655-5e81-8d24-b87bed56562e",
  contractESZ6: "df267b9a-589a-5b94-8d85-a757cf3de44b",
  snapshot6E: "88888888-8888-4888-8888-888888888888",
  snapshotGC: "88888888-8888-4888-8888-888888888801",
  job6E: "77777777-7777-4777-8777-777777777777",
  run6E: "66666666-6666-4666-8666-666666666666",
  jobGC: "77777777-7777-4777-8777-777777777701",
  runGC: "66666666-6666-4666-8666-666666666601",
  thesis6E: "55555555-5555-4555-8555-555555555555",
  thesisGC: "55555555-5555-4555-8555-555555555501",
  artifact6E: "99999999-9999-4999-8999-999999999999",
  artifactGC: "99999999-9999-4999-8999-999999999901",
  conversation6E: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  revision6E: "12121212-1212-4121-8121-121212121212",
  revisionGC: "12121212-1212-4121-8121-121212121201",
  proposal6E: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  featureFvg: "11111111-1111-4111-8111-111111111111",
  featureLevel: "22222222-2222-4222-8222-222222222222",
  featureSweep: "33333333-3333-4333-8333-333333333333",
  featureRsi: "44444444-4444-4444-8444-444444444444",
  routineMorning: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  routineSweep: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  watchlistMetalsFx: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
  watchlistIndex: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee01",
} as const;

export const DATA_REVISION = "fixture-web-1.0.0-6ez6";
export const SESSION_OPEN = "2026-09-22T12:00:00.000Z";
export const BAR_SECONDS = 300;
export const BAR_COUNT = 72;

export function barOpenMs(index: number): number {
  return Date.parse(SESSION_OPEN) + index * BAR_SECONDS * 1000;
}

export function barOpenIso(index: number): string {
  return new Date(barOpenMs(index)).toISOString();
}

export function barCloseIso(index: number): string {
  return new Date(barOpenMs(index) + BAR_SECONDS * 1000).toISOString();
}

export function barUnix(index: number): number {
  return Math.floor(barOpenMs(index) / 1000);
}
