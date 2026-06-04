"use client";

import {
  ArrowLeft,
  Download,
  Loader2,
  Star,
  Calendar,
  Tag,
} from "@/components/ui/icons";
import { useParams, useRouter } from "next/navigation";
import { useState, useCallback } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import {
  useMarketplaceListing,
  useMarketplaceReviews,
  useInstallMarketplaceTemplate,
  useCreateMarketplaceReview,
} from "@/core/marketplace/hooks";

export function MarketplaceDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const listingId = params.id;

  const { listing, isLoading } = useMarketplaceListing(listingId);
  const { reviews } = useMarketplaceReviews(listingId);
  const installMutation = useInstallMarketplaceTemplate(listingId);
  const reviewMutation = useCreateMarketplaceReview(listingId);

  const [installTarget, setInstallTarget] = useState<"private" | "tenant">("private");
  const [installName, setInstallName] = useState("");
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");

  const handleInstall = useCallback(async () => {
    try {
      const result = await installMutation.mutateAsync({
        target_visibility: installTarget,
        target_name: installName || undefined,
      });
      toast.success(t.marketplace.installSuccess);
      router.push(`/workspace/report-templates/editor/${result.target_template_id}`);
    } catch (err) {
      toast.error((err as Error).message || t.marketplace.installFailed);
    }
  }, [installMutation, installTarget, installName, router, t]);

  const handleReview = useCallback(async () => {
    if (!comment.trim()) {
      toast.error(t.marketplace.commentPlaceholder);
      return;
    }
    try {
      await reviewMutation.mutateAsync({ rating, comment });
      toast.success(t.marketplace.reviewSuccess);
      setComment("");
    } catch (err) {
      toast.error((err as Error).message || t.marketplace.reviewFailed);
    }
  }, [reviewMutation, rating, comment, t]);

  if (isLoading || !listing) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 border-b px-6 py-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => router.push("/workspace/template-marketplace")}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">{listing.display_name}</h1>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <Star className="h-3.5 w-3.5" />
              {listing.avg_rating.toFixed(1)} ({listing.review_count} {t.marketplace.reviews})
            </span>
            <span className="flex items-center gap-1">
              <Download className="h-3.5 w-3.5" />
              {listing.install_count} {t.marketplace.install}
            </span>
            {listing.category && (
              <span className="flex items-center gap-1">
                <Tag className="h-3.5 w-3.5" />
                {listing.category}
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Main */}
        <div className="flex-1 overflow-y-auto p-6">
          <Tabs defaultValue="description">
            <TabsList variant="line">
              <TabsTrigger value="description">{t.marketplace.description}</TabsTrigger>
              <TabsTrigger value="reviews">
                {t.marketplace.reviews} ({listing.review_count})
              </TabsTrigger>
            </TabsList>

            <TabsContent value="description" className="mt-4 space-y-4">
              <p className="text-sm leading-relaxed">
                {listing.description || t.marketplace.noDescription}
              </p>

              {listing.tags && listing.tags.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-medium">{t.marketplace.tags}</h3>
                  <div className="flex flex-wrap gap-2">
                    {listing.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded border px-2 py-0.5 text-xs text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {t.marketplace.published} {new Date(listing.created_at).toLocaleDateString()}
                </span>
              </div>
            </TabsContent>

            <TabsContent value="reviews" className="mt-4 space-y-4">
              {/* Review form */}
              <Card>
                <CardHeader>
                  <h3 className="text-sm font-medium">{t.marketplace.writeReview}</h3>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <Label className="text-xs">{t.marketplace.rating}</Label>
                    <div className="flex gap-1">
                      {[1, 2, 3, 4, 5].map((r) => (
                        <button
                          key={r}
                          onClick={() => setRating(r)}
                          className="text-lg"
                        >
                          <Star
                            className={`h-5 w-5 ${r <= rating ? "fill-yellow-400 text-yellow-400" : "text-muted-foreground"}`}
                          />
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs">{t.marketplace.comment}</Label>
                    <Textarea
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      placeholder={t.marketplace.commentPlaceholder}
                      rows={3}
                    />
                  </div>
                  <Button
                    size="sm"
                    onClick={handleReview}
                    disabled={reviewMutation.isPending}
                  >
                    {reviewMutation.isPending ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : null}
                    {t.marketplace.submitReview}
                  </Button>
                </CardContent>
              </Card>

              {/* Reviews list */}
              {reviews.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  {t.marketplace.noReviews}
                </p>
              ) : (
                reviews.map((review) => (
                  <Card key={review.id}>
                    <CardContent className="py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex">
                          {[1, 2, 3, 4, 5].map((r) => (
                            <Star
                              key={r}
                              className={`h-3.5 w-3.5 ${r <= review.rating ? "fill-yellow-400 text-yellow-400" : "text-muted-foreground"}`}
                            />
                          ))}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {review.user_id}
                        </span>
                        <span className="ml-auto text-[10px] text-muted-foreground">
                          {new Date(review.created_at).toLocaleDateString()}
                        </span>
                      </div>
                      {review.comment && (
                        <p className="mt-2 text-sm">{review.comment}</p>
                      )}
                    </CardContent>
                  </Card>
                ))
              )}
            </TabsContent>
          </Tabs>
        </div>

        {/* Sidebar — Install panel */}
        <div className="w-72 shrink-0 border-l p-4">
          <h3 className="mb-3 text-sm font-semibold">{t.marketplace.install}</h3>
          <div className="space-y-3">
            <div>
              <Label className="text-xs">{t.marketplace.installTo}</Label>
              <select
                value={installTarget}
                onChange={(e) =>
                  setInstallTarget(e.target.value as "private" | "tenant")
                }
                className="mt-1 w-full rounded-md border bg-background px-3 py-1.5 text-sm"
              >
                <option value="private">{t.marketplace.installPrivate}</option>
                <option value="tenant">{t.marketplace.installTenant}</option>
              </select>
            </div>

            <div>
              <Label className="text-xs">{t.marketplace.installNamePlaceholder}</Label>
              <Input
                value={installName}
                onChange={(e) => setInstallName(e.target.value)}
                placeholder={listing.display_name}
                className="h-8 text-sm"
              />
            </div>

            <Button
              className="w-full"
              onClick={handleInstall}
              disabled={installMutation.isPending}
            >
              {installMutation.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Download className="mr-1 h-4 w-4" />
              )}
              {t.marketplace.install}
            </Button>

            <p className="text-[10px] text-muted-foreground">
              {t.marketplace.version} {listing.template_version} · {listing.visibility}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
