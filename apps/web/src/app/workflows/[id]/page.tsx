import { NewRunView } from "@/components/NewRunView";

export default async function WorkflowPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <NewRunView workflowId={decodeURIComponent(id)} />;
}
