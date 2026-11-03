import { useId, useState } from "react";

import { useTags } from "@/api/hooks";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface TagInputProps {
  placeholder: string;
  onAdd: (name: string) => void;
  className?: string;
}

/** Text field that suggests existing tags; Enter adds the typed tag (created if new). */
export function TagInput({ placeholder, onAdd, className }: TagInputProps) {
  const tags = useTags();
  const listId = useId();
  const [value, setValue] = useState("");

  const submit = () => {
    const name = value.trim();
    if (!name) return;
    onAdd(name);
    setValue("");
  };

  return (
    <>
      <Input
        value={value}
        list={listId}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          event.stopPropagation(); // typing must not trigger library shortcuts
          if (event.key === "Enter") {
            event.preventDefault();
            submit();
          } else if (event.key === "Escape") {
            setValue("");
            event.currentTarget.blur();
          }
        }}
        className={cn("h-7", className)}
      />
      <datalist id={listId}>
        {tags.data?.map((tag) => <option key={tag.id} value={tag.name} />)}
      </datalist>
    </>
  );
}
