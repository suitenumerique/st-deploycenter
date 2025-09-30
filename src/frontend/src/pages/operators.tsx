import { fetchAPI } from "@/features/api/fetchApi";
import { useQuery } from "@tanstack/react-query";

export default function Operators() {

    const { data, isLoading, error } = useQuery({
        queryKey: ["firstLevelItems"],
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        queryFn: () => fetchAPI("operators/"),
    });


  return <div>Operators</div>;
}