// The status strip under the header on every page: what the automatic runs did last and do next.
import { getAutomationStatus } from "@/lib/data";
import { AutomationStrip } from "./AutomationStrip";

export async function AutomationStatus() {
  const status = await getAutomationStatus();
  return status ? <AutomationStrip status={status} /> : null;
}
