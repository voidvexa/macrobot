import { useEffect, useState } from "react";

// Re-renders on each step boundary (aligned to the wall clock). Only time
// moves here; nothing is fetched.
export function useNow(step = 1000) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let timer;
    const schedule = () => {
      timer = setTimeout(tick, step - (Date.now() % step));
    };
    const tick = () => {
      setNow(Date.now());
      schedule();
    };
    schedule();
    return () => clearTimeout(timer);
  }, [step]);

  return now;
}
