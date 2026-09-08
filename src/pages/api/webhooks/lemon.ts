import { buffer } from 'micro';
import type { NextApiRequest, NextApiResponse } from 'next';
// Note: implement real signature verification per Lemon Squeezy docs.

export const config = { api: { bodyParser: false } };

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const raw = await buffer(req);
  // TODO: verify signature using process.env.LEMON_SQUEEZY_WEBHOOK_SECRET
  let event;
  try {
    event = JSON.parse(raw.toString());
  } catch (err) {
    res.status(400).send('invalid payload');
    return;
  }

  // Minimal fulfillment logic stub. Replace with Supabase SDK calls.
  if (event && event.type === 'order_paid') {
    const order = event.data;
    // Example: map product_handle to allowances and create order record in DB
    // Use SUPABASE_SERVICE_ROLE_KEY to insert into orders and allowances tables server-side.
    console.log('Received order_paid:', order);
    // TODO: call Supabase to create order & grant allowances
  }

  res.status(200).send('ok');
}
