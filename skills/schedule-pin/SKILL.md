---
name: schedule-pin
description: Pin a meeting, call, appointment, deadline or task to a time, so it lands on your calendar with a reminder. Use when the user wants to book, schedule, plan, arrange or set up something with someone, or asks to remind them about it. 用于"预约"、"安排"、"计划"、"约定"、"提醒"、"会议"、"电话"、"见面"、"开会"、"截止日期"、"日程"、"任务"：把会议、电话、见面、截止日期、任务，安排到具体时间，加入日历并设置提醒。
---

A **pin** is one thing fixed to one moment. Pinning it does two things, always
together: the calendar gets the event, and the outbox gets a reminder. One
without the other is half a pin.

## How to pin

1. Resolve relative dates ("next Tuesday", "tomorrow morning") into ISO 8601
   using today's date from the system prompt. Morning = 09:00, afternoon =
   14:00, evening = 18:00 unless the user says otherwise.
2. Check memory for the people involved and **act on** what it knows rather
   than reporting it. Propose a concrete time and pin it: if the user named a
   day but no hour and memory says Alex prefers mornings, pin 9am and say why
   — "since Alex prefers mornings, I pinned 9am". Ask an open question only
   when memory gives you nothing to go on.
3. Call `create_event` with a short, specific title: "Coffee with Alex", not
   "Meeting". Put any agenda or context the user gave into `notes`.
4. Set the reminder. Prefer `create_reminder` when you have it — that is a
   real entry in Apple Reminders, due at the pinned time, which will actually
   notify them. Otherwise call `send_message`, addressed to the user unless
   they asked you to remind someone else. Either way keep it to one line that
   stands on its own when read cold: "Coffee with Alex, Friday 9am — you owe
   him the Berlin numbers."
5. Confirm in one sentence — what, when, with whom — and say which kind of
   reminder they got: one that will notify them at the time
   (`create_reminder`), or a **draft waiting in the outbox** for them to
   review and send (`send_message`). That difference decides whether they
   still have to do something, so say it the first time you pin something
   for someone.

## Edge cases

| Situation | Do |
|---|---|
| Past date requested | Point it out, suggest the next occurrence, pin that once confirmed |
| A deadline or task, no attendee | Pin it the same way; the reminder matters more here than the event does |
| The user only wants a reminder, no calendar entry | Draft the reminder with `send_message` and say the calendar was left alone |
| The user only wants the calendar entry | Create the event and say no reminder was drafted |
| Attendee unknown to memory | Pin it anyway; offer to `save_note` who they are |
| Several things pinned at once | One `create_event` per thing, one reminder covering all of them |
