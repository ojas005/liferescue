import Link from "next/link";
import { CATALOG_ORDER, WORKFLOW_CATALOG } from "@/lib/workflows/catalog";

export function NavBar() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <nav aria-label="Main" className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="text-lg font-bold tracking-tight text-slate-900">
          LifeRescue <span className="font-normal text-slate-500">platform</span>
        </Link>
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <li>
            <Link href="/" className="text-slate-700 hover:text-slate-900">
              Home
            </Link>
          </li>
          {CATALOG_ORDER.map((id) => (
            <li key={id}>
              <Link href={`/workflows/${id}`} className="text-slate-700 hover:text-slate-900">
                {WORKFLOW_CATALOG[id]!.product}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
