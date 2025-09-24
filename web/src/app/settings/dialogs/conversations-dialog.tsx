//import { VerticalAlignBottomOutlined } from "@ant-design/icons";
import { MessageSquareReply, Play, FileText, Newspaper, Users, GraduationCap, CircleCheck, CircleX, CircleAlert, Ellipsis } from "lucide-react";
import { useState } from "react";

import { LoadingAnimation } from "~/components/deer-flow/loading-animation";
import { RainbowText } from "~/components/deer-flow/rainbow-text";
import { Tooltip } from "~/components/deer-flow/tooltip";
import { Button } from "~/components/ui/button";
import {
    Card,
    CardDescription,
    CardHeader,
    CardTitle,
} from "~/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "~/components/ui/dialog";
import { useConversations } from "~/core/api/hooks";
import { cn } from "~/lib/utils";

export function ConversationsDialog() {
    const [open, setOpen] = useState(false);
    // Fetch conversations when dialog opens
    const { results, loading } = useConversations();

    const handleOpenChange = (isOpen: boolean) => {
        setOpen(isOpen);
    }

    const conversations = [
        ...(results ?? []),
        // Placeholder for replays data
        { id: "ai-twin-insurance", data_type: 'txt', title: "Write an article on \"Would you insure your AI twin?\"", date: "2025/5/19 12:54", category: "Social Media", count: 500 },
        { id: "china-food-delivery", data_type: 'txt', title: "如何看待外卖大战", date: "2025/5/20 14:30", category: "Research", count: 1000 },
        { id: "eiffel-tower-vs-tallest-building", data_type: 'txt', title: "How many times taller is the Eiffel Tower than the tallest building in the world?", date: "2025/5/21 16:45", category: "Technology", count: 8 },
        { id: "github-top-trending-repo", data_type: 'txt', title: "Write a brief on the top 1 trending repo on Github today.", date: "2025/5/22 18:00", category: "Education", count: 120 },
        { id: "nanjing-traditional-dishes", data_type: 'txt', title: "Write an article about Nanjing's traditional dishes.", date: "2025/5/23 20:15", category: "Health", count: 60 },
        { id: "rental-apartment-decoration", data_type: 'txt', title: "How to decorate a small rental apartment?", date: "2025/5/23 20:15", category: "Health", count: 116 },
        { id: "review-of-the-professional", data_type: 'txt', title: "Introduce the movie 'Léon: The Professional'", date: "2025/5/23 20:15", category: "Health", count: 678 },
        { id: "ultra-processed-foods", data_type: 'txt', title: "Are ultra-processed foods linked to health?", date: "2025/5/23 20:15", category: "Health", count: 600 },
    ]; // Placeholder for replays data

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <Tooltip title="Conversations" className="max-w-60">
                <DialogTrigger asChild>
                    <Button variant="ghost" size="icon">
                        <MessageSquareReply />
                    </Button>
                </DialogTrigger>
            </Tooltip>
            <DialogContent className="sm:max-w-[860px]">
                <DialogHeader>
                    <DialogTitle>Conversations</DialogTitle>
                    <DialogDescription>
                        Replay your conversations here.
                    </DialogDescription>
                </DialogHeader>
                <div className="flex flex-wrap h-130 w-full overflow-auto border-y">
                    {loading ? (
                        <div className="flex items-center justify-center w-full h-full">
                            <LoadingAnimation />
                        </div>
                    ) : conversations.length === 0 ? (
                        <div className="flex items-center justify-center w-full h-full">
                            <p>No conversations found.</p>
                        </div>
                    ) : (<></>)
                    }
                    {conversations.map((result) => (
                        <div key={result.id} className="flex w-1/1 shrink-2 ">
                            <Card
                                className={cn(
                                    "w-[98%] transition-all duration-300 pt-5 mt-5 rounded-es-none border-0 shadow-none",
                                )}
                            >
                                <div className="flex items-center justify-between">
                                    <div className="pl-4">
                                        {
                                            result.category === "social_media" ? (
                                                <FileText size={32} />
                                            ) : result.category === "news" ? (
                                                <Newspaper size={32} />
                                            ) : result.category === "academic" ? (
                                                <GraduationCap size={32} />
                                            ) : result.category === "popular_science" ? (
                                                <Users size={32} />
                                            ) : (
                                                <Users size={32} />
                                            )
                                        }
                                    </div>
                                    <div className="flex flex-grow items-center">

                                        <CardHeader className={cn("flex-grow pl-3")}>
                                            <CardTitle>
                                                <RainbowText animated={false} className="text-lg inline-block">
                                                    {`${result.title}`}
                                                </RainbowText>
                                            </CardTitle>
                                            <CardDescription>
                                                <RainbowText animated={false} className="text-lg inline-block h-[30px]">
                                                    {`${result.date.substring(0, 19).replace(/-/g, "/").replace("T", " ")} | ${result.category} | ${result.count} messages`}
                                                </RainbowText>
                                                {
                                                    result.count === 0 ? (
                                                        <CircleX size={24} className="text-red-500 inline-block ml-2" />
                                                    ) : result.count > 800 ? (
                                                        <CircleCheck size={24} className="text-green-500 inline-block ml-2" />
                                                    ) : result.count < 800 && result.count > 100 ? (
                                                        <CircleAlert size={24} className="text-yellow-500 inline-block ml-2" />
                                                    ) : (
                                                        <Ellipsis size={32} className="text-gray-500 inline-block ml-2" />
                                                    )
                                                }
                                            </CardDescription>
                                        </CardHeader>
                                    </div>
                                    <div className="pr-4">
                                        <Button className="w-24" onClick={() => {
                                            // Handle replay start logic here
                                            setOpen(false);
                                            // redirect to replay page or start replay session
                                            location.href = `${result.data_type === "txt" ? `/chat?replay=${result.id}` : `/chat?thread_id=${result.id}`}`;

                                        }}>
                                            <Play size={16} />
                                            Replay
                                        </Button>
                                    </div>
                                </div>
                            </Card>
                        </div>
                    ))}

                </div>


                <DialogFooter>
                    <Button variant="outline" onClick={() => setOpen(false)}>
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
