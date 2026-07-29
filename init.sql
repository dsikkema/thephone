-- sqlite
drop table if exists conversations;
drop table if exists sent_messages;
drop table if exists recv_messages;
create table conversations(
  id integer primary key autoincrement,

  -- if ever move to platform without REGEXP function easily includable, just drop
  -- constraint and write app-side validation anew
  participants text not null unique,

  -- default, if expression, must be in parens
  -- default is current unix timestamp as int
  created_at integer not null default (strftime('%s'))
);

-- insert into conversations(participants) values
--   ('10000000000'),
--   ('20000000000'),
--   ('30000000000'),
--   ('40000000000');
-- 
-- select * from conversations;

create table sent_messages(
  id integer primary key autoincrement,
  -- if ever delete, need cascade
  conversation_id integer not null references conversations(id),
  sent_successfully integer,
  content text not null,
  -- note: do not accidentally use "%s" here: double quotes for strings
  -- are technically allowed, but trigger an indication to the engine
  -- that the expression is "non-constant".
  -- note: allowed by sqlite (they regret it; old mysql compatibility concern) but not SQL standard
  sent_at integer not null default (strftime('%s'))
);

create table recv_messages (
  id integer primary key autoincrement,
  conversation_id integer not null references conversations(id),
  sender text not null,
  content text not null,
  recv_at integer not null,
  created_at integer not null default (strftime('%s'))
);

-- insert into sent_messages(conversation_id, sent_successfully, content, sent_at) values
--   (2,
--     true,
--     "Sent message 10 in Conv 2",
--     1781390328+1010
--   ),
--   (2,
--     true,
--     "Sent message 20 in Conv 2",
--     1781390328+1020
--   ),
--   (2,
--     true,
--     "Sent message 30 in Conv 2",
--     1781390328+1030
--   ),
--   (3,
--     true,
--     "Sent message 10 in Conv 3",
--     1781390328+1010
--   ),
--   (3,
--     true,
--     "Sent message 20 in Conv 3",
--     1781390328+1020
--   )
--   ;
-- select * from sent_messages;
-- 
-- insert into recv_messages(conversation_id, sender, content, recv_at)
-- values
--   (1,
--     "10000000000",
--     "Recv message 05 in Conv 1",
--     1781390328+1005
--   ),
--   (2,
--     "10000000000",
--     "Recv message 15 in Conv 2",
--     1781390328+1015
--   ),
--   (2,
--     "10000000000",
--     "Recv message 25 in Conv 2",
--     1781390328+1025
--   );
-- 
-- select * from recv_messages;
-- 
-- select '
-- 
-- All messages:
-- 
-- Sorted by conversation and message send/receive time, interleaving both sent and received
-- 
-- ';
-- with all_messages as (
--   select
--     conversation_id,
--     sender,
--     content,
--     recv_at as msg_time
--   from
--     recv_messages
-- 
--   UNION
-- 
--   select
--     conversation_id,
--     null as sender,
--     content,
--     sent_at as msg_time
--   from 
--     sent_messages
-- )
-- select
--   c.id,
--   c.participants,
--   coalesce(sender, '17777777777'),
--   content,
--   datetime(msg_time, 'unixepoch')
-- from
--   conversations c 
--   -- note: left join to include conversations without messages in them
--   left join all_messages msgs on msgs.conversation_id = c.id
--   order by c.id,msg_time;
