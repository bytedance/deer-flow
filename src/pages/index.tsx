import Link from 'next/link';

export default function Home() {
  return (
    <main className="container mx-auto py-12 px-6">
      <header className="text-center">
        <h1 className="text-4xl font-extrabold">Create Beautiful Children's Books — Fast</h1>
        <p className="mt-4 text-lg text-gray-700">AI story writing, consistent illustrations, lifelike narration, and social-ready videos — polished and kid-safe.</p>
        <div className="mt-6 flex justify-center gap-4">
          <a href="/checkout/founder" className="bg-indigo-600 text-white px-6 py-3 rounded-md shadow">Reserve Founder Seat — $129 (Limited)</a>
          <a href="/demo" className="border px-6 py-3 rounded-md">Try a free 2‑page demo (watermarked)</a>
        </div>
      </header>

      <section className="mt-12 grid md:grid-cols-3 gap-8">
        <div className="p-6 border rounded">
          <h3 className="font-semibold">Starter — $9.99</h3>
          <p className="mt-2 text-sm">Up to 8 pages, 1 character, 720p narrated MP4 (~60s), PDF/ePub.</p>
        </div>

        <div className="p-6 border rounded">
          <h3 className="font-semibold">Standard — $19.99</h3>
          <p className="mt-2 text-sm">Up to 24 pages, 2 characters, 1080p up to 3m.</p>
        </div>

        <div className="p-6 border rounded">
          <h3 className="font-semibold">Deluxe — $34.99</h3>
          <p className="mt-2 text-sm">Up to 48 pages, premium art, artist polish (5 pages), commercial license.</p>
        </div>
      </section>

      <section className="mt-12">
        <h2 className="text-2xl font-bold">Founder Offer (limited)</h2>
        <p className="mt-2 text-gray-700">One-time $129. Includes the equivalent of 30 Starter books, 15 video minutes (1080p), 200 TTS minutes, two team seats, and priority processing — valid 24 months.</p>
        <div className="mt-4">
          <a href="/checkout/founder" className="bg-yellow-500 px-5 py-3 rounded-md font-bold">Reserve Founder Seat — 50 seats only</a>
        </div>
      </section>

      <footer className="mt-16 text-center text-sm text-gray-500">
        <p>Kid-safe. Parental controls. No sensitive data collection without consent.</p>
      </footer>
    </main>
  );
}
