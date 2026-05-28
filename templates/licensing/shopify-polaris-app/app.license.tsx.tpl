/**
 * app.license.tsx — Polaris UI for license status & activation.
 * Route: /app/license (en el embedded admin)
 */
import { json, type LoaderFunctionArgs } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";
import { Banner, BlockStack, Card, Page, Text, DataTable } from "@shopify/polaris";
import { authenticate } from "../shopify.server";
import { getLicenseStatus } from "../lib/license.server";

export async function loader({ request }: LoaderFunctionArgs) {
  const { session } = await authenticate.admin(request);
  const status = await getLicenseStatus(session.shop);
  return json({ status, shop: session.shop });
}

export default function LicensePage() {
  const { status, shop } = useLoaderData<typeof loader>();
  return (
    <Page title="License status">
      <BlockStack gap="500">
        <Card>
          {status.valid ? (
            <Banner tone="success" title="License active">
              <Text as="p">
                The app is licensed for <strong>{shop}</strong>.
              </Text>
            </Banner>
          ) : (
            <Banner tone="critical" title="License invalid">
              <Text as="p">{(status as any).error}</Text>
            </Banner>
          )}
        </Card>

        {status.valid && (status as any).claims && (
          <Card>
            <BlockStack gap="200">
              <Text as="h3" variant="headingSm">License claims</Text>
              <DataTable
                columnContentTypes={["text", "text"]}
                headings={["Claim", "Value"]}
                rows={Object.entries((status as any).claims).map(([k, v]) => [
                  k,
                  typeof v === "string" ? v : JSON.stringify(v),
                ])}
              />
            </BlockStack>
          </Card>
        )}
      </BlockStack>
    </Page>
  );
}
