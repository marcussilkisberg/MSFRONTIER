-- 018_cure_not_a_stage.sql: "Resetting the immune system" is a way of acting on the immune attack, not a stage of the
-- disease. Its approaches (immune reconstitution, CAR-T and tolerance, stem cell transplantation) move to the Immune
-- attack stage, and the separate Reset stage is removed from the map. The research area itself becomes
-- "Towards a cure" on the site, a view across stages. Run after 017. Safe to re-run.

update bank.open_questions set stage_id = 'immune' where stage_id = 'reset';
update bank.map_stage_nodes set stage_id = 'immune' where stage_id = 'reset';
delete from bank.map_stages where stage_id = 'reset';

update bank.map_stages
   set question = 'Which immune cells drive relapses, and can they be stopped or reset?'
 where stage_id = 'immune';
