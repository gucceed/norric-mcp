-- T2_007: Monthly quota function for Free tier enforcement
-- Quota resets on the 1st at 00:00 Europe/Stockholm
-- Free tier: 25 lookups/month. Silver: 500. Guld: 2000. Premium: unlimited.

CREATE OR REPLACE FUNCTION current_month_quota(p_user_id uuid)
RETURNS TABLE (
    used        bigint,
    allowance   int,
    remaining   int,
    resets_at   timestamptz
) LANGUAGE sql STABLE AS $$
    WITH monthly_count AS (
        SELECT COUNT(*) AS used
        FROM query_log
        WHERE user_id = p_user_id
          AND queried_at >= DATE_TRUNC('month',
                NOW() AT TIME ZONE 'Europe/Stockholm'
              ) AT TIME ZONE 'Europe/Stockholm'
    ),
    user_tier_row AS (
        SELECT tier FROM users WHERE id = p_user_id
    ),
    allowance AS (
        SELECT CASE (SELECT tier FROM user_tier_row)
            WHEN 'free'       THEN 25
            WHEN 'silver'     THEN 500
            WHEN 'guld'       THEN 2000
            WHEN 'premium'    THEN 2147483647  -- effectively unlimited
            WHEN 'enterprise' THEN 2147483647
        END AS allowance
    )
    SELECT
        (SELECT used FROM monthly_count)::bigint,
        (SELECT allowance FROM allowance)::int,
        GREATEST(
            0,
            (SELECT allowance FROM allowance) -
            (SELECT used FROM monthly_count)::int
        )::int,
        (
            DATE_TRUNC('month', NOW() AT TIME ZONE 'Europe/Stockholm')
            + INTERVAL '1 month'
        ) AT TIME ZONE 'Europe/Stockholm'
$$;
