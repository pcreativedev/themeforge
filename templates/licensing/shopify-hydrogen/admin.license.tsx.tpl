/**
 * Admin route — license status panel.
 * Route: /admin/license
 *
 * Loader: returns license state.
 * UI: shows whether the license is valid + claims (sub/domain/type/exp).
 *
 * Protect this route in production (basic auth, IP whitelist, etc.).
 */
import { json, type LoaderFunctionArgs } from "@shopify/remix-oxygen";
import { useLoaderData } from "@remix-run/react";
import { getLicenseStatus } from "~/lib/license.server";

export async function loader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  const status = await getLicenseStatus(url.host);
  return json(status);
}

export default function AdminLicense() {
  const status = useLoaderData<typeof loader>();
  return (
    <div style={{ padding: 32, fontFamily: "system-ui", maxWidth: 720 }}>
      <h1>License status — __PROJECT__</h1>
      <p>
        Backend: <code>__LICENSE_API_URL__</code>
      </p>
      <p>
        Status:{" "}
        {status.valid ? (
          <strong style={{ color: "#16a34a" }}>VALID</strong>
        ) : (
          <strong style={{ color: "#dc2626" }}>INVALID — {(status as any).error}</strong>
        )}
      </p>
      {status.valid && (status as any).claims && (
        <table style={{ borderCollapse: "collapse", marginTop: 16 }}>
          <tbody>
            {Object.entries((status as any).claims).map(([k, v]) => (
              <tr key={k}>
                <td style={{ padding: 6, borderBottom: "1px solid #eee" }}>
                  <strong>{k}</strong>
                </td>
                <td style={{ padding: 6, borderBottom: "1px solid #eee" }}>
                  <code>{JSON.stringify(v)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
