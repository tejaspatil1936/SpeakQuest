import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

test("renders the masthead", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "SpeakQuest" })).toBeInTheDocument();
});
